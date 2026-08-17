"""Per-request correlation id.

One id ties a provider request, its activity id, the status transitions, the
database write, the portfolio run, and the rendered result together. It is a
random opaque value and never encodes a credential.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

HEADER_NAME = "X-Correlation-ID"


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str:
    """Return the current id, creating one if this runs outside a request."""
    current = _correlation_id.get()
    if current is None:
        current = new_correlation_id()
        _correlation_id.set(current)
    return current
