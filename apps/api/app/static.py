"""Serve the built Vite frontend from the same origin as the API.

Mounting `StaticFiles` at `/` does not catch client-side routes such as
`/scenarios/new` — FastAPI returns its own JSON 404 instead. Production
therefore mounts hashed `/assets` and uses an explicit SPA fallback for
everything that is not `/api/*`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def _safe_file(dist_dir: Path, relative: str) -> Path | None:
    if not relative or relative.endswith("/"):
        return None
    dist_root = dist_dir.resolve()
    candidate = (dist_root / relative).resolve()
    try:
        candidate.relative_to(dist_root)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def mount_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """Mount hashed assets and the SPA fallback. Returns whether it was mounted."""
    index = dist_dir / "index.html"
    if not index.is_file():
        return False

    assets = dist_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def spa_root() -> FileResponse:
        return FileResponse(index)

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon() -> FileResponse:
        path = _safe_file(dist_dir, "favicon.svg")
        if path is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(path)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        existing = _safe_file(dist_dir, full_path)
        if existing is not None:
            return FileResponse(existing)
        return FileResponse(index)

    return True
