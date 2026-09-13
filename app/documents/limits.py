from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PdfLimits:
    max_size_mb: int = 20
    max_pages: int = 100
    max_characters: int = 200000
    min_characters: int = 20
    page_characters: int = 20000
    extraction_timeout: float = 60
    summary_timeout: float = 180
    max_chunks: int = 20
    chunk_characters: int = 10000
    spoken_characters: int = 300
    selection_timeout: float = 60
    memory_mb: int = 512

    def __post_init__(self):
        bounds = {"max_size_mb": 100, "max_pages": 500, "max_characters": 1000000, "min_characters": 1000000,
                  "page_characters": 50000, "max_chunks": 50, "chunk_characters": 12000,
                  "spoken_characters": 1000, "memory_mb": 1024}
        for key, maximum in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("Invalid PDF resource limit")
        if self.min_characters > self.max_characters:
            raise ValueError("PDF minimum characters cannot exceed the maximum")
        for key in ("extraction_timeout", "summary_timeout", "selection_timeout"):
            value = getattr(self, key)
            if not math.isfinite(value) or not 0 < value <= 600:
                raise ValueError("Invalid PDF timeout")

    @classmethod
    def from_settings(cls, settings):
        return cls(**{name: getattr(settings, "pdf_" + name) for name in cls.__dataclass_fields__})
