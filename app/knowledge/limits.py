from dataclasses import dataclass
import math
import os


@dataclass(frozen=True)
class KnowledgeLimits:
    chunk_chars: int = 1800
    chunk_overlap: int = 250
    top_k: int = 6
    min_similarity: float = .25
    max_documents: int = 500
    max_chunks_per_document: int = 500
    max_total_chunks: int = 50000
    max_file_bytes: int = 20971520
    index_timeout: float = 600
    query_timeout: float = 120
    max_answer_chars: int = 6000
    max_index_bytes: int = 536870912
    max_dimension: int = 4096
    max_depth: int = 4
    max_entries: int = 10000
    per_document: int = 2

    def __post_init__(self):
        caps = dict(chunk_chars=8000, chunk_overlap=4000, top_k=10, max_documents=500,
                    max_chunks_per_document=500, max_total_chunks=50000, max_file_bytes=20971520,
                    max_answer_chars=6000, max_index_bytes=536870912, max_dimension=4096,
                    max_depth=8, max_entries=10000, per_document=5)
        for key, cap in caps.items():
            value = getattr(self, key)
            if type(value) is not int or not (0 if key == 'chunk_overlap' else 1) <= value <= cap:
                raise ValueError('Invalid knowledge resource limit.')
        if self.chunk_chars < 64 or self.chunk_overlap >= self.chunk_chars // 2:
            raise ValueError('Chunk overlap must be less than half the chunk size.')
        for key, cap in [('index_timeout', 600), ('query_timeout', 120)]:
            value = getattr(self, key)
            if isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= cap:
                raise ValueError('Invalid knowledge timeout.')
        if isinstance(self.min_similarity, bool) or not math.isfinite(self.min_similarity) or not 0 <= self.min_similarity <= 1:
            raise ValueError('Invalid similarity threshold.')

    @classmethod
    def from_environment(cls):
        defaults = cls()
        return cls(**{key: (float if isinstance(getattr(defaults, key), float) else int)(os.environ['VOXPILOT_KNOWLEDGE_' + key.upper()])
                      for key in cls.__dataclass_fields__ if 'VOXPILOT_KNOWLEDGE_' + key.upper() in os.environ})
