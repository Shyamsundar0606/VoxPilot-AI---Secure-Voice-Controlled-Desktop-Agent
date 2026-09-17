"""Version 1: SQLite transactions containing metadata, text and little-endian float32 vectors."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import numpy as np
from app.knowledge.discovery import safe_source
from app.knowledge.embedding import validate_vector

VERSION = 1


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


class IndexStore:
    def __init__(self, path, limits):
        self.path, self.limits = Path(path), limits

    @contextmanager
    def connect(self, check=None):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if any(p.is_symlink() or p.is_junction() for p in (self.path, *self.path.parents)):
            raise ValueError('Linked index rejected.')
        if self.path.exists() and self.path.stat().st_size > self.limits.max_index_bytes:
            raise ValueError('Index size limit exceeded.')
        connection = sqlite3.connect(self.path, timeout=1)
        try:
            if check:
                def progress():
                    try: check(); return 0
                    except Exception: return 1
                connection.set_progress_handler(progress, 1000)
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA secure_delete=ON')
            connection.execute('PRAGMA journal_mode=DELETE')
            page_size = connection.execute('PRAGMA page_size').fetchone()[0]
            connection.execute(f'PRAGMA max_page_count={max(1, self.limits.max_index_bytes // page_size)}')
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version == 0:
                if connection.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone():
                    raise ValueError('Unversioned index rejected; no automatic migration.')
                with connection:
                    connection.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                    connection.execute('CREATE TABLE documents (id TEXT PRIMARY KEY, metadata TEXT NOT NULL)')
                    connection.execute('CREATE TABLE chunks (id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, metadata TEXT NOT NULL, vector BLOB NOT NULL, checksum TEXT NOT NULL)')
                    connection.execute('CREATE TABLE scopes (root TEXT PRIMARY KEY, formats TEXT NOT NULL)')
                    connection.execute('PRAGMA user_version=1')
            elif version != VERSION: raise ValueError('Unsupported index schema version; index was not migrated.')
            if connection.execute('PRAGMA quick_check').fetchone() != ('ok',): raise ValueError('Knowledge index is corrupt.')
            if connection.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Orphan index rows rejected.')
            self.check_limits(connection)
            yield connection
        except sqlite3.Error:
            raise ValueError('Knowledge index is unavailable, corrupt or exceeds its storage limit.') from None
        finally:
            connection.close()

    def check_limits(self, db):
        for table, cap in [('documents', self.limits.max_documents), ('chunks', self.limits.max_total_chunks)]:
            if db.execute('SELECT count(*) FROM ' + table).fetchone()[0] > cap: raise ValueError('Knowledge index count limit exceeded.')
        size = db.execute('SELECT coalesce(sum(length(metadata)+length(vector)),0) FROM chunks').fetchone()[0]
        if size > self.limits.max_index_bytes: raise ValueError('Knowledge index size limit exceeded.')
        if db.execute('SELECT 1 FROM documents WHERE length(metadata)>4096 LIMIT 1').fetchone(): raise ValueError('Invalid document metadata size.')
        if db.execute('SELECT 1 FROM chunks WHERE length(metadata)>? OR length(vector)>? LIMIT 1',
                      (self.limits.chunk_chars * 12 + 4096, self.limits.max_dimension * 4)).fetchone():
            raise ValueError('Invalid chunk storage size.')

    def documents(self, db):
        result = []
        for identifier, raw in db.execute('SELECT id, metadata FROM documents ORDER BY id'):
            if len(raw) > 4096: raise ValueError('Invalid document metadata.')
            item = json.loads(raw)
            if item['id'] != identifier or not isinstance(identifier, str) or len(identifier) != 32: raise ValueError('Invalid document identity.')
            safe_source(item['relative'])
            if item['status'] != 'indexed' or len(item['hash']) != 64: raise ValueError('Invalid document metadata.')
            result.append(item)
        return sorted(result, key=lambda item: (item['root'], item['relative'].casefold(), item['id']))

    def put(self, db, item, chunks):
        db.execute('INSERT OR REPLACE INTO documents VALUES (?,?)', (item['id'], canonical(item)))
        for chunk, vector in chunks:
            raw, blob = canonical(chunk), vector.astype('<f4').tobytes()
            checksum = hashlib.sha256(raw.encode() + blob).hexdigest()
            db.execute('INSERT INTO chunks VALUES (?,?,?,?,?)', (chunk['id'], item['id'], raw, blob, checksum))
        self.check_limits(db)

    def rows(self, db, dimension):
        for identifier, document_id, raw, blob, checksum in db.execute('SELECT id, document_id, metadata, vector, checksum FROM chunks ORDER BY id'):
            if len(raw) > self.limits.chunk_chars * 12 + 4096 or len(blob) != dimension * 4:
                raise ValueError('Invalid stored chunk size.')
            if hashlib.sha256(raw.encode() + blob).hexdigest() != checksum: raise ValueError('Corrupt chunk checksum.')
            chunk = json.loads(raw)
            if chunk['id'] != identifier or chunk['document_id'] != document_id: raise ValueError('Corrupt chunk identity.')
            safe_source(chunk['relative'])
            if not 0 < len(chunk['text']) <= self.limits.chunk_chars: raise ValueError('Invalid chunk text.')
            vector = validate_vector(np.frombuffer(blob, dtype='<f4').tolist(), dimension, self.limits.max_dimension)
            yield chunk, vector

    @staticmethod
    def revision(db):
        return hashlib.sha256(canonical(list(db.execute('SELECT id, metadata FROM documents ORDER BY id'))).encode()).hexdigest()
