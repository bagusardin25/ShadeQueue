"""Event loop configuration.

psycopg's async mode cannot run on Windows' default `ProactorEventLoop`, so a
selector loop has to be used instead. This is a no-op on Linux, which is what
the production container runs.

Two entry points, because they are reached differently:

* `configure_event_loop()` sets the policy and covers everything that goes
  through `asyncio.run` — Alembic, the ingestion scripts, pytest-asyncio. It
  must run before the loop is created.
* `new_event_loop()` is a loop factory for uvicorn. uvicorn 0.36+ calls
  `asyncio.run(..., loop_factory=...)`, which bypasses the policy entirely and
  hard-codes `ProactorEventLoop` on Windows, so the factory has to be passed in
  explicitly as `loop="app.runtime:new_event_loop"`.
"""

from __future__ import annotations

import asyncio
import sys


def configure_event_loop() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def new_event_loop() -> asyncio.AbstractEventLoop:
    """Loop factory for uvicorn's `--loop app.runtime:new_event_loop`."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
