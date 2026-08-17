"""Declarative base and shared column helpers."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk():
    return mapped_column(primary_key=True, default=uuid.uuid4)


def utc_now_column(**kwargs):
    """A timezone-aware timestamp defaulting to the database clock.

    Using `now()` on the server keeps ordering consistent even if an application
    instance has a skewed clock.
    """
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kwargs)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
