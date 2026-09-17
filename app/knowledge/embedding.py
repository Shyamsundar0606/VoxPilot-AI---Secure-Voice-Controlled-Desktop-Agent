import numpy as np


def validate_vector(value, dimension=None, maximum=4096):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError('Invalid embedding dimensions.')
    if any(type(x) not in (int, float) for x in value): raise ValueError('Invalid embedding numbers.')
    if dimension is not None and len(value) != dimension: raise ValueError('Inconsistent embedding dimensions.')
    with np.errstate(over='ignore', invalid='ignore'):
        vector = np.asarray(value, dtype='<f4')
    norm = np.linalg.norm(vector.astype(np.float64))
    if not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 0:
        raise ValueError('Embedding contains nonfinite or zero values.')
    return (vector / norm).astype('<f4')


class Embedder:
    def __init__(self, client, limits):
        self.client, self.limits, self.model = client, limits, client.model

    def embed(self, text, cancel, timeout, query=False, dimension=None):
        if not isinstance(text, str) or not text or len(text) > max(1000, self.limits.chunk_chars):
            raise ValueError('Embedding input exceeds limits.')
        # Nomic's retrieval prefixes are data, never paths or execution parameters.
        payload = {'model': self.model, 'input': ('search_query: ' if query else 'search_document: ') + text, 'truncate': False}
        result = self.client.request('embed', payload, cancel, min(timeout, 60))
        try:
            vectors = result.get('embeddings')
            if not isinstance(vectors, list) or len(vectors) != 1: raise ValueError('Invalid embedding response.')
            return validate_vector(vectors[0], dimension, self.limits.max_dimension)
        finally:
            result.clear()
