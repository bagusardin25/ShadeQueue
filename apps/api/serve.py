"""Serve the API and the built SPA from one origin.

    npm run serve
    uv run --project apps/api python apps/api/serve.py

By default this rebuilds `apps/web/dist`, then starts uvicorn. FastAPI mounts
that dist at `/` so the same port answers `/api/*` and the planner UI.

    SKIP_FRONTEND_BUILD=1   keep the existing dist
    RELOAD=1                watch the API package (default off for this entry)
    HOST / PORT             bind address (127.0.0.1:8000)

uvicorn hard-codes `ProactorEventLoop` on Windows, which psycopg's async mode
cannot use, so the loop factory is passed explicitly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import uvicorn

LOOP_FACTORY = "app.runtime:new_event_loop"
REPO_ROOT = Path(__file__).resolve().parents[2]
API_DIR = Path(__file__).resolve().parent
WEB_DIST = REPO_ROOT / "apps" / "web" / "dist"


def _npm() -> str:
    found = shutil.which("npm.cmd") or shutil.which("npm")
    if not found:
        raise SystemExit("npm is required to build the frontend. Install Node.js 22+.")
    return found


def build_frontend() -> None:
    if os.environ.get("SKIP_FRONTEND_BUILD", "0") == "1":
        if not (WEB_DIST / "index.html").is_file():
            raise SystemExit(f"SKIP_FRONTEND_BUILD=1 but {WEB_DIST / 'index.html'} is missing.")
        print(f"Using existing frontend build at {WEB_DIST}", flush=True)
        return
    print("Building frontend (apps/web)…", flush=True)
    completed = subprocess.run([_npm(), "run", "build"], cwd=REPO_ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if not (WEB_DIST / "index.html").is_file():
        raise SystemExit(f"Frontend build finished without {WEB_DIST / 'index.html'}.")


if __name__ == "__main__":
    if str(API_DIR) not in sys.path:
        sys.path.insert(0, str(API_DIR))
    os.chdir(API_DIR)
    build_frontend()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving API + SPA at http://{host}:{port}", flush=True)
    reload = os.environ.get("RELOAD", "0") == "1"
    run_kwargs: dict = {
        "app": "app.main:app",
        "host": host,
        "port": port,
        "reload": reload,
        "loop": LOOP_FACTORY,
        "log_level": "info",
    }
    if reload:
        run_kwargs["reload_dirs"] = [str(API_DIR)]
    uvicorn.run(**run_kwargs)
