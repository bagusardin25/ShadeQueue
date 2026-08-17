"""Domain error types.

Every error carries a stable machine-readable `code` so the frontend can map it
to one of the required UI states without parsing prose. No error message may
contain a credential, a database URL, or a raw provider payload.
"""

from __future__ import annotations


class ShadeQueueError(Exception):
    """Base class for errors that are safe to surface to an API client."""

    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class InvalidAOIError(ShadeQueueError):
    code = "INVALID_AOI"
    http_status = 422


class DateNotAllowedError(ShadeQueueError):
    code = "DATE_NOT_ALLOWED"
    http_status = 422


class LiveRunLimitError(ShadeQueueError):
    code = "LIVE_RUN_LIMIT_REACHED"
    http_status = 429


class ProviderTimeoutError(ShadeQueueError):
    code = "PROVIDER_TIMEOUT"
    http_status = 504


class ProviderRateLimitError(ShadeQueueError):
    code = "PROVIDER_RATE_LIMIT"
    http_status = 429


class ProviderFailedError(ShadeQueueError):
    code = "PROVIDER_FAILED"
    http_status = 502


class ProviderUnavailableError(ShadeQueueError):
    """A 5xx from the provider: the request was well formed, the service was not."""

    code = "PROVIDER_UNAVAILABLE"
    http_status = 502


class MalformedProviderResponseError(ShadeQueueError):
    code = "MALFORMED_PROVIDER_RESPONSE"
    http_status = 502


class ProviderNotConfiguredError(ShadeQueueError):
    code = "PROVIDER_NOT_CONFIGURED"
    http_status = 503


class ResourceNotFoundError(ShadeQueueError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(ShadeQueueError):
    code = "CONFLICT"
    http_status = 409


class EmptyCorridorError(ShadeQueueError):
    code = "EMPTY_CORRIDOR"
    http_status = 422


class InfeasibleConstraintsError(ShadeQueueError):
    code = "INFEASIBLE_CONSTRAINTS"
    http_status = 422


#: Provider failures that justify another status check rather than failing the
#: job. A heatmap *submission* is never blindly repeated (plan section 14).
TRANSIENT_PROVIDER_CODES = frozenset(
    {
        ProviderTimeoutError.code,
        ProviderRateLimitError.code,
        ProviderUnavailableError.code,
    }
)


def is_transient(error: ShadeQueueError) -> bool:
    return error.code in TRANSIENT_PROVIDER_CODES
