import re


class OutputBuffer:
    def __init__(self, max_bytes=262144, max_lines=500):
        if not 1 <= max_bytes <= 1048576 or not 1 <= max_lines <= 5000: raise ValueError("Invalid output limits")
        self.max_bytes, self.max_lines = max_bytes, max_lines
        self.lines, self.pending = [], bytearray()

    def append(self, data):
        for part in data.splitlines(keepends=True):
            self.pending.extend(part[:self.max_bytes - len(self.pending)])
            if part.endswith((b"\n", b"\r")) or len(self.pending) >= self.max_bytes:
                text = self.pending.decode("utf-8", errors="replace")
                # Redact complete sensitive assignments, including values containing spaces.
                if re.search(r"token|key|secret|password|credential|auth|bearer", text, re.I): text = "[Sensitive output redacted]\n"
                text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
                self.lines.append(text)
                self.pending[:] = b""
                while len(self.lines) > self.max_lines or len("".join(self.lines).encode("utf-8")) > self.max_bytes:
                    self.lines.pop(0)

    def text(self): return "".join(self.lines)

    def clear(self): self.lines.clear(); self.pending[:] = b""
