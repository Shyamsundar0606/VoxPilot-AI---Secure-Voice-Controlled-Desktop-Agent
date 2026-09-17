"""Bounded metadata discovery and identity checks, run in an isolated worker."""
from collections import deque
from pathlib import PurePosixPath
import hashlib
import os
import re
import stat
from app.filesystem.roots import ApprovedRoots
from app.documents.extraction import identity
from app.security.filesystem_policy import safe_relative

SKIP = {'node_modules', 'dist', 'build', 'target', 'logs', 'log', 'databases', '__pycache__', 'coverage', 'secrets', 'credentials'}
SENSITIVE = re.compile(r'(?:^|[_. -])(env|key|keys|certificate|certificates|token|tokens|secret|secrets|credential|credentials|password|passwords|id_rsa|id_ed25519|logs?|databases?)(?:[_. -]|$)', re.I)


def safe_source(relative):
    relative = safe_relative(relative)
    parts = PurePosixPath(relative).parts
    if not parts or any(p.casefold() in SKIP or SENSITIVE.search(p) for p in parts):
        raise ValueError('Sensitive or excluded document name.')
    if PurePosixPath(relative).suffix.lower() not in {'.pdf', '.txt', '.md'}:
        raise ValueError('Unsupported knowledge source.')
    return relative


def discover(configuration, root, formats, limits, progress=lambda *_: None):
    roots = ApprovedRoots(roots=configuration[0], settings_path=configuration[1])
    roots.resolve(root)
    queue, result, visited = deque([('', 0)]), [], 0
    while queue:
        relative, depth = queue.popleft()
        for item in roots.resolve(root, relative).iterdir():
            visited += 1
            if visited > limits.max_entries: raise ValueError('Discovery entry limit reached; narrow the approved folder.')
            rel = '/'.join(filter(None, (relative, item.name)))
            try:
                if item.name.casefold() in SKIP or SENSITIVE.search(item.name): continue
                path = roots.resolve(root, rel)
                info = path.stat(follow_symlinks=False)
            except (ValueError, OSError): continue
            if stat.S_ISDIR(info.st_mode):
                if depth >= limits.max_depth:
                    raise ValueError('Discovery depth limit reached; approve a narrower folder.')
                queue.append((rel, depth + 1))
            elif stat.S_ISREG(info.st_mode) and path.suffix.lower() in ({'.pdf'} if formats == 'pdf' else {'.pdf', '.txt', '.md'}):
                safe_source(rel)
                if info.st_size > limits.max_file_bytes: raise ValueError('A source exceeds the file-size limit.')
                result.append({'root': root, 'relative': rel, 'identity': identity(info), 'size': info.st_size,
                               'mtime': info.st_mtime_ns, 'type': path.suffix.lower()})
                if len(result) > limits.max_documents: raise ValueError('Document limit reached.')
    return sorted(result, key=lambda row: row['relative'].casefold())


def fingerprint(configuration, item, limits, progress=lambda *_: None):
    roots = ApprovedRoots(roots=configuration[0], settings_path=configuration[1])
    safe_source(item['relative'])
    path = roots.resolve(item['root'], item['relative'])
    digest, total = hashlib.sha256(), 0
    with path.open('rb') as stream:
        if identity(os.fstat(stream.fileno())) != tuple(item['identity']): raise ValueError('Source changed.')
        while block := stream.read(65536):
            total += len(block)
            if total > limits.max_file_bytes: raise ValueError('Source too large.')
            digest.update(block)
        if identity(os.fstat(stream.fileno())) != tuple(item['identity']): raise ValueError('Source changed.')
    if identity(roots.resolve(item['root'], item['relative']).stat()) != tuple(item['identity']): raise ValueError('Source changed.')
    return digest.hexdigest()
