"""Development entry point.

    uv run --project apps/api python apps/api/serve.py

uvicorn hard-codes `ProactorEventLoop` on Windows, which psycopg's async mode
cannot use, so the loop factory is passed explicitly. The same flag works with
the plain CLI:

    uvicorn app.main:app --loop app.runtime:new_event_loop
"""

from __future__ import annotations

import os

import uvicorn

LOOP_FACTORY = "app.runtime:new_event_loop"

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("RELOAD", "1") == "1",
        reload_dirs=[os.path.dirname(os.path.abspath(__file__))],
        loop=LOOP_FACTORY,
        log_level="info",
    )
