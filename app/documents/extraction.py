"""Read only, sequential PDF extraction inside the bounded parser process."""
from collections import deque
from dataclasses import dataclass
import os
import re
import stat
from threading import Event
import unicodedata

from app.documents.policy import PdfArgs, allowed_document_root
from app.documents.errors import DocumentError, DocumentFailureCode, SAFE_MESSAGES
from app.filesystem.roots import ApprovedRoots
from app.security.filesystem_policy import safe_component, FilePolicyError

SCANNED_MESSAGE = SAFE_MESSAGES[DocumentFailureCode.INSUFFICIENT_TEXT]


@dataclass(frozen=True)
class PdfChoice:
    root: str
    relative: str
    identity: tuple

    @property
    def label(self):
        return f"{self.root} / {self.relative}"


def identity(info):
    # Python 3.12 Windows path stat and fstat disagree about ctime semantics.
    # Compare stable file identity, size and last-write time instead.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def locate(configuration, arguments, max_depth=4, progress=lambda *_: None):
    roots = ApprovedRoots(roots=configuration[0], settings_path=configuration[1])
    args = PdfArgs.model_validate(arguments)
    keys = [key for key in roots.snapshot() if allowed_document_root(key)] if args.root == "all" else [args.root]
    if args.root != "all": roots.resolve(args.root)
    queue = deque((key, "", 0) for key in keys)
    matches, visited = [], 0
    while queue:
        root, relative, depth = queue.popleft()
        try:
            directory = roots.resolve(root, relative)
            for child in directory.iterdir():
                visited += 1
                if visited > 10000: raise DocumentError("PDF search limit reached. Use a more specific filename and root.")
                rel = "/".join(filter(None, (relative, child.name)))
                try:
                    safe_component(child.name)
                    checked = roots.resolve(root, rel)
                    info = checked.stat(follow_symlinks=False)
                except (ValueError, OSError): continue
                if stat.S_ISDIR(info.st_mode) and depth < max_depth:
                    queue.append((root, rel, depth + 1))
                elif stat.S_ISREG(info.st_mode) and child.suffix.lower() == ".pdf":
                    query = args.query.casefold()
                    if (query == child.name.casefold() if query.endswith(".pdf") else query in child.stem.casefold()):
                        matches.append(PdfChoice(root, rel, identity(info)))
                        if len(matches) > 20: raise DocumentError("Too many matching PDFs. Use a more specific filename and root.")
        except OSError:
            if args.root != "all": raise DocumentError("The PDF location is unavailable or inaccessible.") from None
        except ValueError as exc:
            if isinstance(exc, DocumentError): raise
            if args.root != "all": raise DocumentError("The PDF location is not approved or accessible.") from None
    return sorted(matches, key=lambda choice: choice.label.casefold())


def normalize_text(text):
    text = "".join(c for c in text if c in "\n\t\r" or not unicodedata.category(c).startswith("C"))
    return re.sub(r"\s+", " ", text).strip()


def extract(configuration, choice, limits, progress=lambda *_: None, cancel=None, reader_factory=None):
    cancel = cancel or Event()
    def check():
        if cancel.is_set(): raise DocumentError(DocumentFailureCode.CANCELLED)
    roots = ApprovedRoots(roots=configuration[0], settings_path=configuration[1])
    pages = []
    try:
        check()
        if not allowed_document_root(choice.root): raise DocumentError(DocumentFailureCode.UNAPPROVED_ROOT)
        path = roots.resolve(choice.root, choice.relative)
        info = path.stat(follow_symlinks=False)
        if path.suffix.lower() != ".pdf" or not stat.S_ISREG(info.st_mode): raise DocumentError(DocumentFailureCode.NOT_PDF)
        if identity(info) != choice.identity: raise DocumentError(DocumentFailureCode.FILE_CHANGED)
        if info.st_size > limits.max_size_mb * 1024**2: raise DocumentError(DocumentFailureCode.FILE_TOO_LARGE)
        check()
        path = roots.resolve(choice.root, choice.relative)  # Last path-policy check before opening.
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or identity(opened) != choice.identity:
                raise DocumentError(DocumentFailureCode.FILE_CHANGED)
            if stream.read(5) != b"%PDF-": raise DocumentError(DocumentFailureCode.INVALID_SIGNATURE)
            stream.seek(0)
            if reader_factory is None:
                from pypdf import PdfReader
                reader_factory = PdfReader
            reader = reader_factory(stream, strict=True)
            if reader.is_encrypted: raise DocumentError(DocumentFailureCode.ENCRYPTED)
            count = len(reader.pages)
            if count == 0: raise DocumentError(DocumentFailureCode.EMPTY)
            if count > limits.max_pages: raise DocumentError(DocumentFailureCode.PAGE_LIMIT)
            total, empty, truncated = 0, 0, False
            for index in range(count):
                check()
                raw = reader.pages[index].extract_text()
                if not isinstance(raw, str): raise DocumentError(DocumentFailureCode.EXTRACTION_FAILED)
                text = normalize_text(raw)
                raw = ""
                remaining = min(limits.page_characters, limits.max_characters - total)
                if len(text) > remaining: text, truncated = text[:remaining], True
                pages.append((index + 1, text)); total += len(text)
                if not text: empty += 1
                progress("Extracting PDF", f"Page {index + 1} of {count}")
                check()
                if truncated or total >= limits.max_characters:
                    truncated = truncated or index + 1 < count
                    break
            if identity(os.fstat(stream.fileno())) != choice.identity or identity(roots.resolve(choice.root, choice.relative).stat()) != choice.identity:
                raise DocumentError(DocumentFailureCode.CHANGED_DURING_EXTRACTION)
            if sum(len(re.sub(r"\W", "", text)) for _, text in pages) < limits.min_characters:
                raise DocumentError(DocumentFailureCode.INSUFFICIENT_TEXT)
            return {"pages": pages, "truncated": truncated, "empty_pages": empty, "page_count": count}
    except DocumentError:
        pages.clear(); raise
    except MemoryError:
        pages.clear(); raise DocumentError(DocumentFailureCode.RESOURCE_LIMIT) from None
    except (OSError, FilePolicyError):
        pages.clear(); raise DocumentError(DocumentFailureCode.INACCESSIBLE) from None
    except ImportError:
        pages.clear(); raise DocumentError(DocumentFailureCode.DEPENDENCY_UNAVAILABLE) from None
    except Exception:
        pages.clear(); raise DocumentError(DocumentFailureCode.MALFORMED) from None
