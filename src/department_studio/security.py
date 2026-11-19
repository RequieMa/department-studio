"""Local browser authority, kept separate from per-delivery runtime credentials."""

import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class OwnerCredential:
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)

    def matches(self, value: str) -> bool:
        return value.isascii() and secrets.compare_digest(self.token, value)


def allowed_request(origin: str, host: str | None, request_origin: str | None) -> bool:
    return host == urlsplit(origin).netloc and request_origin in (None, origin)
