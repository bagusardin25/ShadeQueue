"""Serve the built Vite frontend from the same origin as the API.

In production a multi-stage Docker build copies `apps/web/dist` into the runtime
image, so FastAPI answers both `/api/*` and the application shell. In local
development the Vite dev server proxies `/api` here instead and this mount stays
inactive.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Static files with a client-side routing fallback.

    Unknown paths return `index.html` so a deep link such as
    `/portfolios/<id>` survives a hard refresh. API paths never reach here
    because their routers are registered first.
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            index = Path(self.directory) / "index.html"
            if index.is_file():
                return FileResponse(index)
            raise


def mount_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """Mount the SPA when a build exists. Returns whether it was mounted."""
    if not (dist_dir / "index.html").is_file():
        return False
    app.mount("/", SpaStaticFiles(directory=str(dist_dir), html=True), name="frontend")
    return True
