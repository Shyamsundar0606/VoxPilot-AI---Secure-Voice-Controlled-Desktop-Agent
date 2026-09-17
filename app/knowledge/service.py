"""Knowledge operations coordinate policy, isolated reads, atomic writes and evidence-only answers."""
import hashlib
import json
from pathlib import PurePosixPath
from threading import Event, Lock, RLock
from time import monotonic
from uuid import uuid4
from app.documents.limits import PdfLimits
from app.documents.process import run_isolated
from app.knowledge import answers
from app.knowledge.chunking import chunk_pages
from app.knowledge.citations import render_sources
from app.knowledge.discovery import discover, fingerprint
from app.knowledge.extraction import extract_source
from app.knowledge.policy import validate_arguments
from app.knowledge.retrieval import retrieve
from app.knowledge.storage import canonical
from app.models import ExecutionResult, Status


def outcome(message, success=True, **kwargs):
    return ExecutionResult(original_command='[Local knowledge operation]', normalized_command='',
                           selected_tool='knowledge_operation', store_history=False,
                           status=Status.COMPLETED if success else Status.FAILED,
                           result_message=message, spoken_message='The document result and full sources are visible.' if success else 'The document operation could not be completed.', **kwargs)


class KnowledgeService:
    def __init__(self, roots, store, embedder, answer_client, limits, pdf_limits=None, isolate=run_isolated, clock=monotonic):
        self.roots, self.store, self.embedder, self.answer_client = roots, store, embedder, answer_client
        self.limits, self.pdf_limits, self.isolate, self.clock = limits, pdf_limits or PdfLimits(), isolate, clock
        self._operation, self._state = Lock(), RLock()
        self._pending = self._selection = None
        self._last_sources = []

    def cancel(self):
        with self._state:
            self._pending = self._selection = None

    def close(self):
        self.cancel()
        self._last_sources.clear()

    def _signature(self):
        return canonical({'model': self.embedder.model, 'chunk_chars': self.limits.chunk_chars,
                          'overlap': self.limits.chunk_overlap, 'vector_format': 'float32-le-v1'})

    def execute(self, request=None, cancel_event=None, progress=lambda *_: None, confirmation=None, selection=None, open_source=None):
        cancel = cancel_event or Event()
        if not self._operation.acquire(blocking=False): return outcome('A knowledge operation is already running.', False)
        started = self.clock()
        budget = self.limits.index_timeout if request and request.tool_name in {'index_documents', 'refresh_document_index'} else self.limits.query_timeout
        def check():
            if cancel.is_set(): raise ValueError('Knowledge operation cancelled.')
            remaining = budget - (self.clock() - started)
            if remaining <= 0: raise ValueError('Knowledge operation timed out.')
            return remaining
        def isolated(operation, args):
            return self.isolate(operation, args, self.pdf_limits, cancel, progress,
                                timeout=min(check(), self.pdf_limits.extraction_timeout))
        try:
            check()
            index_path = self.store.path.resolve()
            if any(index_path.is_relative_to(path.resolve()) for path in self.roots.snapshot().values()):
                raise ValueError('The knowledge index must be outside approved source folders.')
            with self.store.connect(check) as db:
                if confirmation: return self._confirm(db, confirmation, check)
                if selection:
                    with self._state:
                        pending, self._selection = self._selection, None
                    if not pending or selection[0] != pending['token'] or self.clock() >= pending['expires']:
                        raise ValueError('Selection expired.')
                    if type(selection[1]) is not int or not 1 <= selection[1] <= len(pending['ids']): raise ValueError('Invalid selection.')
                    return self._propose(db, [pending['ids'][selection[1] - 1]], 'remove', check)
                if open_source:
                    return self._open_source(db, open_source, isolated, check)
                args = validate_arguments(request.tool_name, request.arguments)
                name = request.tool_name
                if name in {'index_documents', 'refresh_document_index'}:
                    self._last_sources.clear()
                    return self._index(db, args if name == 'index_documents' else None, cancel, progress, check, isolated)
                docs = self.store.documents(db)
                if name == 'list_indexed_documents':
                    approved = []
                    for doc in docs:
                        check()
                        try: self.roots.resolve(doc['root'], doc['relative'])
                        except (ValueError, OSError): continue
                        approved.append(doc)
                    return outcome('\n'.join(f"{d['root']}/{d['relative']} — {d['page_count'] or 'text'} pages — indexed" for d in approved) or 'No indexed documents.',
                                   knowledge_data={'count': len(approved), 'roots': self._roots()})
                if name in {'remove_indexed_document', 'clear_document_index'}:
                    if name == 'clear_document_index': return self._propose(db, [d['id'] for d in docs], 'clear', check)
                    matches = [d for d in docs if args['filename'].casefold() in {d['relative'].casefold(), PurePosixPath(d['relative']).name.casefold()}]
                    if not matches: raise ValueError('No matching indexed document.')
                    if len(matches) > 20: raise ValueError('Too many matches; use a relative filename.')
                    if len(matches) == 1: return self._propose(db, [matches[0]['id']], 'remove', check)
                    token = uuid4().hex
                    with self._state:
                        self._selection = {'token': token, 'expires': self.clock() + 60, 'ids': [d['id'] for d in matches]}
                    return outcome('Choose the indexed document to remove.', document_selection={'kind': 'knowledge', 'token': token,
                                   'timeout': 60, 'labels': [d['root'] + '/' + d['relative'] for d in matches]})
                return self._query(db, name, args, docs, cancel, progress, check, isolated)
        except Exception as exc:
            from app.documents.errors import DocumentError
            if cancel.is_set():
                return outcome('Knowledge operation cancelled; incomplete index changes were rolled back.', False).model_copy(update={'status': Status.CANCELLED})
            # Only local messages; never echo parser/model/OS exceptions or document text.
            from app.knowledge.transport import KnowledgeSetupError
            message = str(exc) if isinstance(exc, (DocumentError, KnowledgeSetupError)) else 'Knowledge operation failed safely. Check approved sources, limits, index integrity and locally installed Ollama models.'
            return outcome(message, False)
        finally:
            self._operation.release()

    def _roots(self):
        return [key for key in self.roots.snapshot() if key in {'desktop', 'documents', 'downloads'} or key.startswith(('project_', 'document_'))]

    def _index(self, db, args, cancel, progress, check, isolated):
        scopes = [(args['root'], args['formats'])] if args else list(db.execute('SELECT root, formats FROM scopes ORDER BY root'))
        if not scopes: return outcome('Select an approved source and index it first.', False)
        existing = self.store.documents(db)
        signature = db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone()
        if signature and signature[0] != self._signature(): raise ValueError('Embedding configuration changed; clear the index first.')
        dimension_row = db.execute("SELECT value FROM metadata WHERE key='dimension'").fetchone()
        dimension = int(dimension_row[0]) if dimension_row else None
        reused, indexed, all_chunks = 0, 0, 0
        with db:
            db.execute('BEGIN IMMEDIATE')
            for root, formats in scopes:
                check(); progress('Processing', 'Discovering approved documents')
                if args is None and root not in self.roots.snapshot():
                    for document in existing:
                        if document['root'] == root: db.execute('DELETE FROM documents WHERE id=?', (document['id'],))
                    db.execute('DELETE FROM scopes WHERE root=?', (root,))
                    continue
                items = isolated(discover, (self.roots.configuration(), root, formats, self.limits))
                old = [d for d in existing if d['root'] == root]
                present_paths = {item['relative'].casefold() for item in items}
                by_path = {d['relative'].casefold(): d for d in old}
                remaining = {d['id']: d for d in old}
                observed = set()
                for number, item in enumerate(items):
                    check(); progress('Processing', f'Indexing document {number + 1} of {len(items)}')
                    digest = isolated(fingerprint, (self.roots.configuration(), item, self.limits))
                    previous = by_path.get(item['relative'].casefold())
                    if previous is None:
                        renamed = [d for d in remaining.values() if d['relative'].casefold() not in present_paths and d['hash'] == digest and tuple(d['identity'][:2]) == tuple(item['identity'][:2])]
                        if len(renamed) == 1: previous = renamed[0]
                    identifier = previous['id'] if previous else uuid4().hex
                    observed.add(identifier); remaining.pop(identifier, None)
                    if previous and previous['hash'] == digest:
                        # Path changes update metadata but do not re-embed unchanged content.
                        updated = {**previous, **item}
                        db.execute('UPDATE documents SET metadata=? WHERE id=?', (canonical(updated), identifier))
                        if previous['relative'] != item['relative']:
                            for chunk_id, raw, vector in list(db.execute('SELECT id, metadata, vector FROM chunks WHERE document_id=?', (identifier,))):
                                chunk = json.loads(raw); chunk['relative'] = item['relative']; raw = canonical(chunk)
                                db.execute('UPDATE chunks SET metadata=?, checksum=? WHERE id=?', (raw, hashlib.sha256(raw.encode() + vector).hexdigest(), chunk_id))
                        reused += 1
                        continue
                    extracted, chunks, encoded = None, [], []
                    try:
                        extracted = isolated(extract_source, (self.roots.configuration(), item, self.pdf_limits, self.limits))
                        chunks = chunk_pages(identifier, item['relative'], extracted['pages'], self.limits, check)
                        extracted['pages'].clear()
                        all_chunks += len(chunks)
                        if all_chunks > self.limits.max_total_chunks: raise ValueError('Operation chunk limit exceeded.')
                        for index, chunk in enumerate(chunks):
                            progress('Processing', f'Embedding chunk {index + 1} of {len(chunks)}')
                            vector = self.embedder.embed(chunk['text'], cancel, check(), dimension=dimension)
                            if dimension is None: dimension = len(vector)
                            if len(vector) != dimension: raise ValueError('Inconsistent dimensions.')
                            encoded.append((chunk, vector))
                        if isolated(fingerprint, (self.roots.configuration(), item, self.limits)) != digest: raise ValueError('Source changed during indexing.')
                        check()
                        self.store.put(db, {**item, 'id': identifier, 'hash': digest, 'page_count': extracted['page_count'], 'status': 'indexed'}, encoded)
                        indexed += 1
                    finally:
                        if extracted: extracted['pages'].clear()
                        for _, vector in encoded: vector.fill(0)
                        encoded.clear(); chunks.clear()
                for document in old:
                    if document['id'] not in observed: db.execute('DELETE FROM documents WHERE id=?', (document['id'],))
                db.execute('INSERT OR REPLACE INTO scopes VALUES (?,?)', (root, formats))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('signature',?)", (self._signature(),))
            if dimension: db.execute("INSERT OR REPLACE INTO metadata VALUES ('dimension',?)", (str(dimension),))
            self.store.check_limits(db)
            check()
        return outcome(f'Index updated: {indexed} document(s) embedded, {reused} unchanged. Stale entries removed.',
                       knowledge_data={'count': len(self.store.documents(db)), 'roots': self._roots()})

    def _current(self, doc, isolated, check):
        try:
            check()
            # Fingerprint checks policy, complete identity and hash, including replaced files.
            return isolated(fingerprint, (self.roots.configuration(), doc, self.limits)) == doc['hash']
        except Exception:
            check()
            return False

    def _query(self, db, name, args, docs, cancel, progress, check, isolated):
        dimension_row = db.execute("SELECT value FROM metadata WHERE key='dimension'").fetchone()
        if not dimension_row: return outcome(answers.INSUFFICIENT, knowledge_data={'sources': [], 'answer': answers.INSUFFICIENT, 'count': 0, 'roots': self._roots()})
        dimension = int(dimension_row[0])
        if not 1 <= dimension <= self.limits.max_dimension: raise ValueError('Corrupt dimensions.')
        if db.execute("SELECT value FROM metadata WHERE key='signature'").fetchone() != (self._signature(),): raise ValueError('Embedding configuration changed.')
        progress('Processing', 'Revalidating indexed sources')
        valid = {d['id']: d for d in docs if self._current(d, isolated, check)}
        chunks = []
        question_vector = None
        try:
            if name == 'show_answer_sources':
                chunks = [chunk for chunk, _ in self.store.rows(db, dimension) if chunk['id'] in self._last_sources and chunk['document_id'] in valid]
                message = 'Sources for the last answer.' if chunks else 'No current sources for the last answer.'
            else:
                self._last_sources.clear()
                question_vector = self.embedder.embed(args['query'], cancel, check(), query=True, dimension=dimension)
                chunks = retrieve(self.store.rows(db, dimension), question_vector, valid, self.limits, check)
                message = 'Retrieved local source excerpts.' if chunks else answers.INSUFFICIENT
                if name == 'ask_documents' and chunks:
                    progress('Processing', 'Generating answer from retrieved evidence')
                    try:
                        message, cited = answers.generate(args['query'], chunks, self.answer_client, self.limits, cancel, check())
                        chunks = [c for c in chunks if c['id'] in cited]
                    except Exception:
                        check()
                        message = 'Answer generation unavailable or invalid. Retrieved source excerpts are shown below.'
            # Recheck after the model call, not only before it.
            if any(not self._current(valid[c['document_id']], isolated, check) for c in chunks):
                self._last_sources.clear()
                raise ValueError('Source changed during answer generation.')
            sources = render_sources(chunks, valid)
            check()
            self._last_sources = [c['id'] for c in chunks]
            return outcome(message, knowledge_data={'answer': message, 'sources': sources, 'count': len(valid), 'roots': self._roots()})
        finally:
            if question_vector is not None: question_vector.fill(0)
            chunks.clear()

    def _propose(self, db, identifiers, action, check):
        check()
        docs = {d['id']: d for d in self.store.documents(db)}
        if any(key not in docs for key in identifiers): raise ValueError('Indexed document changed.')
        plan = canonical({'action': action, 'ids': sorted(identifiers), 'revision': self.store.revision(db)})
        digest, token = hashlib.sha256(plan.encode()).hexdigest(), uuid4().hex
        with self._state:
            self._pending = (token, digest, plan, self.clock() + 30)
        details = 'Clear the complete local document index?' if action == 'clear' else 'Remove from index: ' + ', '.join(docs[i]['root'] + '/' + docs[i]['relative'] for i in identifiers)
        return outcome(details, confirmation={'kind': 'knowledge', 'token': token, 'hash': digest, 'timeout': 30,
                                              'details': details + '\nOriginal source files will remain untouched.'})

    def _confirm(self, db, confirmation, check):
        with self._state:
            pending, self._pending = self._pending, None
        if not pending or tuple(confirmation) != pending[:2] or self.clock() >= pending[3]: raise ValueError('Confirmation expired or invalid.')
        if hashlib.sha256(pending[2].encode()).hexdigest() != pending[1]: raise ValueError('Changed action.')
        plan = json.loads(pending[2])
        with db:
            db.execute('BEGIN IMMEDIATE')
            if plan['revision'] != self.store.revision(db): raise ValueError('Index changed since confirmation.')
            check()
            if plan['action'] == 'clear':
                for table in ('chunks', 'documents', 'metadata', 'scopes'): db.execute('DELETE FROM ' + table)
            else:
                for identifier in plan['ids']: db.execute('DELETE FROM documents WHERE id=?', (identifier,))
            check()
        self._last_sources.clear()
        return outcome('Index updated. Original source files were not changed.', knowledge_data={'count': len(self.store.documents(db)), 'sources': [], 'answer': '', 'roots': self._roots()})

    def _open_source(self, db, chunk_id, isolated, check):
        if chunk_id not in self._last_sources: raise ValueError('Source is not from the last answer.')
        row = db.execute('SELECT document_id FROM chunks WHERE id=?', (chunk_id,)).fetchone()
        docs = {d['id']: d for d in self.store.documents(db)}
        if not row or row[0] not in docs or not self._current(docs[row[0]], isolated, check): raise ValueError('Source no longer approved.')
        doc = docs[row[0]]
        check()
        # Reuse the Windows filesystem adapter. No raw path can enter via command/model arguments.
        self.roots.platform.open_document(self.roots.resolve(doc['root'], doc['relative']))
        return outcome('Approved source opened.')
