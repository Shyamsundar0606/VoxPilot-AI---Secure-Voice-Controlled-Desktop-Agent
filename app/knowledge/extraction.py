import os
import re
import unicodedata
from app.documents.extraction import extract, PdfChoice, identity
from app.filesystem.roots import ApprovedRoots
from app.knowledge.discovery import safe_source


def extract_source(configuration, item, pdf_limits, limits, progress=lambda *_: None):
    safe_source(item['relative'])
    if item['type'] == '.pdf':
        result = extract(configuration, PdfChoice(item['root'], item['relative'], tuple(item['identity'])), pdf_limits, progress)
        if result['truncated']:
            result['pages'].clear()
            raise ValueError('PDF exceeds character limits; partial documents are not indexed.')
        return result
    roots = ApprovedRoots(roots=configuration[0], settings_path=configuration[1])
    path = roots.resolve(item['root'], item['relative'])
    raw = bytearray()
    try:
        with path.open('rb') as stream:
            if identity(os.fstat(stream.fileno())) != tuple(item['identity']): raise ValueError('Source changed.')
            raw.extend(stream.read(min(limits.max_file_bytes, pdf_limits.max_characters * 4) + 1))
            if len(raw) > min(limits.max_file_bytes, pdf_limits.max_characters * 4): raise ValueError('Text size limit exceeded.')
            if identity(os.fstat(stream.fileno())) != tuple(item['identity']): raise ValueError('Source changed.')
        if identity(roots.resolve(item['root'], item['relative']).stat()) != tuple(item['identity']): raise ValueError('Source changed.')
        if b'\0' in raw: raise ValueError('Binary text file rejected.')
        text = raw.decode('utf-8-sig', 'replace')
        if len(text) > pdf_limits.max_characters: raise ValueError('Text character limit exceeded.')
        text = ''.join(c for c in text if c in '\n\r\t' or not unicodedata.category(c).startswith('C'))
        text = '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()).strip()
        if not text: raise ValueError('Document contains no text.')
        return {'pages': [(None, text)], 'page_count': None}
    finally:
        raw[:] = b'\0' * len(raw)
        raw.clear()
