from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from datetime import timedelta
from threading import Lock
from time import monotonic

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from .database import utcnow

password_hasher = PasswordHasher()


def hash_password(value: str) -> str:
    return password_hasher.hash(value)


def verify_password(encoded: str, value: str) -> bool:
    try:
        return password_hasher.verify(encoded, value)
    except VerifyMismatchError:
        return False


def opaque_token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class LoginLimiter:
    def __init__(self, attempts: int = 5, window_seconds: int = 300):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.entries: dict[str, deque[float]] = defaultdict(deque)
        self.lock = Lock()

    def allowed(self, key: str) -> bool:
        now = monotonic()
        with self.lock:
            row = self.entries[key]
            while row and row[0] < now - self.window_seconds:
                row.popleft()
            return len(row) < self.attempts

    def fail(self, key: str) -> None:
        with self.lock:
            self.entries[key].append(monotonic())

    def clear(self, key: str) -> None:
        with self.lock:
            self.entries.pop(key, None)


def enrollment_expiry():
    return utcnow() + timedelta(minutes=10)
