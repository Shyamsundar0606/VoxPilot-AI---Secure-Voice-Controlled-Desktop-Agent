import hashlib
import re


def chunk_pages(document_id, relative, pages, limits, check=lambda: None):
    chunks = []
    for page, text in pages:
        start, heading = 0, None
        while start < len(text):
            check()
            end = min(len(text), start + limits.chunk_chars)
            if end < len(text):
                boundary = text.rfind(' ', start + limits.chunk_chars // 2, end)
                if boundary > start: end = boundary
            piece = text[start:end].strip()
            headings = re.findall(r'^#{1,6} (.+)$', text[:end], re.M)
            if headings: heading = headings[-1][:200]
            if piece:
                sequence = len(chunks)
                digest = hashlib.sha256(f'{document_id}\0{page}\0{sequence}\0{piece}'.encode()).hexdigest()
                chunks.append(dict(id=digest, document_id=document_id, relative=relative, page=page,
                                   heading=heading, sequence=sequence, start=start, end=end, text=piece))
                if len(chunks) > limits.max_chunks_per_document: raise ValueError('Document chunk limit exceeded.')
            if end == len(text): break
            next_start = max(start + 1, end - limits.chunk_overlap)
            while next_start < end and next_start > 0 and not text[next_start - 1].isspace(): next_start += 1
            start = next_start
    return chunks
