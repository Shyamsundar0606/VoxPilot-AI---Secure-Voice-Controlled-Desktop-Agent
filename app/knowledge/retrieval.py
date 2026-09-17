import hashlib
import numpy as np


def retrieve(rows, question_vector, allowed, limits, check):
    candidates = []
    for chunk, vector in rows:
        check()
        if chunk['document_id'] not in allowed: continue
        score = float(np.dot(question_vector, vector))
        if score >= limits.min_similarity:
            candidates.append((score, chunk))
            # Bound candidate text while preserving enough for document diversity.
            if len(candidates) > limits.top_k * limits.max_documents * 2:
                candidates.sort(key=lambda item: (-item[0], item[1]['id']))
                candidates = candidates[:limits.top_k * limits.max_documents]
    candidates.sort(key=lambda item: (-item[0], item[1]['id']))
    result, counts, hashes, context_chars = [], {}, set(), 0
    for score, chunk in candidates:
        check()
        doc = chunk['document_id']
        digest = hashlib.sha256(chunk['text'].encode()).hexdigest()
        if digest in hashes or counts.get(doc, 0) >= limits.per_document: continue
        if context_chars + len(chunk['text']) > 24000: continue
        if any(old['document_id'] == doc and old['page'] == chunk['page'] and
               min(old['end'], chunk['end']) > max(old['start'], chunk['start']) for old in result): continue
        result.append({**chunk, 'score': score})
        context_chars += len(chunk['text'])
        hashes.add(digest); counts[doc] = counts.get(doc, 0) + 1
        if len(result) == limits.top_k: break
    return result
