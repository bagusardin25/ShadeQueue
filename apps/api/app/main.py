"""ShadeQueue application entry point.

A single-origin modular monolith: one FastAPI service exposes `/api/v1`, serves
the built frontend, and talks to one PostGIS database.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import health, v1_router
from app.api.schemas import ErrorResponse
from app.config import WEB_DIST_DIR, settings
from app.db.session import dispose_engine
from app.domain.errors import ShadeQueueError
from app.services.correlation import HEADER_NAME, get_correlation_id, new_correlation_id, set_correlation_id
from app.static import mount_frontend

logger = logging.getLogger("shadequeue")

DESCRIPTION = """
ShadeQueue ranks candidate bus-stop shade shelter sites for one Phoenix corridor
by combining FortyGuard heat exposure, official bus-stop attributes, and CDC/ATSDR
Social Vulnerability Index data.

It recommends candidates. It does not authorize capital expenditure and does not
claim any reduction in temperature, illness, or mortality. A qualified human
planner owns the final decision.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not settings.provider_configured:
        logger.warning("FORTYGUARD_API_KEY is not set; heat jobs will run in DEMO_FIXTURE mode.")
    elif not settings.live_provider_enabled:
        logger.info("Provider key present but LIVE_PROVIDER_ENABLED is false; using fixtures.")
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ShadeQueue API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["content-type", HEADER_NAME],
            expose_headers=[HEADER_NAME],
        )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        incoming = request.headers.get(HEADER_NAME, "")
        # An inbound id is echoed only when it looks like our own opaque token,
        # so a caller cannot inject arbitrary text into the audit trail.
        if len(incoming) == 32 and all(char in "0123456789abcdef" for char in incoming.lower()):
            correlation = incoming.lower()
        else:
            correlation = new_correlation_id()
        set_correlation_id(correlation)
        response = await call_next(request)
        response.headers[HEADER_NAME] = correlation
        return response

    @app.middleware("http")
    async def body_size_limit(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = 0
            if declared > settings.max_request_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content=ErrorResponse(
                        code="PAYLOAD_TOO_LARGE",
                        message="The request body exceeds the permitted size.",
                        detail={"maxBytes": settings.max_request_body_bytes},
                        correlation_id=get_correlation_id(),
                    ).model_dump(by_alias=True),
                )
        return await call_next(request)

    @app.exception_handler(ShadeQueueError)
    async def domain_error_handler(request: Request, exc: ShadeQueueError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=ErrorResponse(
                code=exc.code,
                message=exc.message,
                detail=exc.detail,
                correlation_id=get_correlation_id(),
            ).model_dump(by_alias=True),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code="VALIDATION_ERROR",
                message="The request did not match the expected schema.",
                detail={"errors": _safe_validation_detail(exc)},
                correlation_id=get_correlation_id(),
            ).model_dump(by_alias=True),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # The correlation id is the only thing the client gets; the trace stays
        # in the server log so no internal detail leaks into a response.
        logger.exception("Unhandled error [correlation_id=%s]", get_correlation_id())
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                code="INTERNAL_ERROR",
                message="The request could not be completed.",
                correlation_id=get_correlation_id(),
            ).model_dump(by_alias=True),
        )

    app.include_router(health.router)
    app.include_router(v1_router)

    # Mounted last so every API route wins the path match.
    if mount_frontend(app, WEB_DIST_DIR):
        logger.info("Serving SPA from %s", WEB_DIST_DIR)
    else:
        logger.warning(
            "SPA not mounted (%s/index.html missing). API-only mode. Run `npm run build`.",
            WEB_DIST_DIR,
        )
    return app


def _safe_validation_detail(exc: RequestValidationError) -> list[dict]:
    """Field locations and messages only, never the submitted values."""
    return [
        {"location": [str(part) for part in error.get("loc", [])], "message": error.get("msg", "")}
        for error in exc.errors()
    ]


app = create_app()
