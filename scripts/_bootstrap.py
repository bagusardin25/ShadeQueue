"""Shared bootstrap for the ingestion scripts.

Puts `apps/api` on the import path so the scripts reuse the application's
settings, models, and session handling instead of duplicating them.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "apps" / "api"

if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from app.runtime import configure_event_loop

configure_event_loop()

FIXTURES_DIR = REPO_ROOT / "fixtures"
