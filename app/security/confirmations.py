"""One-shot, expiring write proposals. Authorization is never a model field."""
from dataclasses import dataclass
from secrets import token_urlsafe
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class PendingCreation:
    token: str
    request_json: str
    identity: tuple
    expires: float


class Confirmations:
    def __init__(self, timeout=30.0, clock=monotonic):
        if not 0 < timeout <= 300: raise ValueError("Invalid confirmation timeout")
        self.timeout, self.clock = timeout, clock
        self._lock, self._pending = Lock(), None

    def propose(self, request, identity):
        with self._lock:
            self._pending = PendingCreation(token_urlsafe(24), request.model_dump_json(), tuple(identity), self.clock() + self.timeout)
            return self._pending.token

    def take(self, token):
        with self._lock:
            pending, self._pending = self._pending, None
            if pending and pending.token == token and self.clock() < pending.expires: return pending
            return None

    def cancel(self):
        with self._lock: self._pending = None
