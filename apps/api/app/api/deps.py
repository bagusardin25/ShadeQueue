"""Request-scoped dependencies."""

from __future__ import annotations

import hashlib

from fastapi import Request

from app.db.session import get_session  # noqa: F401  (re-exported for routers)


def client_fingerprint(request: Request) -> str | None:
    """A stable, non-identifying key for per-client live-run limits.

    The client IP is hashed rather than stored, and a proxy header is honoured
    only for its first hop. This is a credit guard, not an authentication
    mechanism, and it is not durable against a determined caller.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        raw = forwarded.split(",")[0].strip()
    elif request.client is not None:
        raw = request.client.host
    else:
        return None
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]
