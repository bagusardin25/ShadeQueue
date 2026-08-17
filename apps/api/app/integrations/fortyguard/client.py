"""HTTP client for the FortyGuard Temperature API.

Both calls carry explicit connect and read timeouts. Failures are classified so
the caller can tell a retryable status check from a permanent failure; a heatmap
*submission* is never retried automatically, because each one may cost credit.

The API key is read from settings, sent as a header, and never logged, echoed
into an error message, or written into `provider_response`.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.config import ProviderDefaults, Settings
from app.config import settings as default_settings
from app.domain.errors import (
    MalformedProviderResponseError,
    ProviderFailedError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.integrations.fortyguard.schemas import (
    ParsedHeatmapResult,
    parse_status_response,
    parse_submit_response,
)

ProviderStatus = ParsedHeatmapResult


class HeatmapProvider(Protocol):
    """The contract both the live client and the fixture provider satisfy."""

    async def submit_heatmap(self, body: dict[str, Any]) -> tuple[str, dict[str, Any]]: ...

    async def check_status(self, activity_id: str) -> tuple[ParsedHeatmapResult, dict[str, Any]]: ...


class FortyGuardClient:
    def __init__(self, config: Settings | None = None, client: httpx.AsyncClient | None = None):
        self._settings = config or default_settings
        self._client = client

    # --- plumbing ---

    def _headers(self) -> dict[str, str]:
        if not self._settings.fortyguard_api_key:
            raise ProviderNotConfiguredError(
                "The FortyGuard API key is not configured for this deployment."
            )
        value = f"{self._settings.fortyguard_api_key_prefix}{self._settings.fortyguard_api_key}"
        return {
            self._settings.fortyguard_api_key_header: value,
            "accept": "application/json",
            "content-type": "application/json",
        }

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._settings.provider_connect_timeout_seconds,
            read=self._settings.provider_read_timeout_seconds,
            write=self._settings.provider_read_timeout_seconds,
            pool=self._settings.provider_connect_timeout_seconds,
        )

    async def _request(self, method: str, path: str, *, json_body: Any = None) -> Any:
        url = self._settings.fortyguard_base_url.rstrip("/") + path
        headers = self._headers()

        async def _send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.request(method, url, json=json_body, headers=headers)

        try:
            if self._client is not None:
                response = await _send(self._client)
            else:
                async with httpx.AsyncClient(timeout=self._timeout()) as client:
                    response = await _send(client)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "The provider did not respond within the configured timeout."
            ) from exc
        except httpx.TransportError as exc:
            # Connection reset, DNS failure, TLS problem: treat as unavailable
            # rather than as a failed activity.
            raise ProviderUnavailableError("The provider could not be reached.") from exc

        return self._decode(response)

    def _decode(self, response: httpx.Response) -> Any:
        status = response.status_code

        if status == 429:
            raise ProviderRateLimitError("The provider rate limit was reached.")
        if status >= 500:
            raise ProviderUnavailableError(
                "The provider returned a server error.", detail={"providerStatus": status}
            )
        if status == 401 or status == 403:
            # Deliberately vague: never hint at the credential's contents.
            raise ProviderFailedError(
                "The provider rejected this deployment's credentials.",
                detail={"providerStatus": status},
            )
        if status >= 400:
            raise ProviderFailedError(
                "The provider rejected the request.", detail={"providerStatus": status}
            )

        try:
            return response.json()
        except ValueError as exc:
            raise MalformedProviderResponseError(
                "The provider returned a non-JSON body.",
                detail={"providerStatus": status, "contentType": response.headers.get("content-type")},
            ) from exc

    # --- operations ---

    async def submit_heatmap(self, body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Submit a heatmap request and return (activity_id, raw response)."""
        payload = await self._request("POST", ProviderDefaults.HEATMAP_PATH, json_body=body)
        activity_id = parse_submit_response(payload)
        return activity_id, _as_storable(payload)

    async def check_status(self, activity_id: str) -> tuple[ParsedHeatmapResult, dict[str, Any]]:
        """Check one activity and return (parsed result, raw response)."""
        path = ProviderDefaults.STATUS_PATH.format(activity_id=activity_id)
        payload = await self._request("GET", path)
        return parse_status_response(payload), _as_storable(payload)


#: Heat surfaces can be large. The raw provider body is kept for the audit trail
#: with the bulky geometry stripped, since the polygons are already persisted as
#: rows in `heat_cells`.
_STRIPPED_KEYS = ("map_data", "mapData", "geojson", "result_data", "heatmap")


def _as_storable(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"nonObjectResponse": True}
    stored: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _STRIPPED_KEYS:
            stored[key] = {"omitted": "stored as heat_cells rows"}
        elif isinstance(value, dict):
            stored[key] = _as_storable(value)
        else:
            stored[key] = value
    return stored
