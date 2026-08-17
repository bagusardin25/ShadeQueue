"""Source snapshot provenance.

Every portfolio run records the snapshots that actually produced its numbers,
not merely the newest snapshots in the table, so an old run stays auditable
after a re-ingestion.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SourceSnapshot
from app.domain.runtime_mode import RuntimeMode, effective_runtime_mode

PHOENIX_SOURCE_NAME = "City of Phoenix bus stops"
SVI_SOURCE_NAME = "CDC/ATSDR SVI"
FORTYGUARD_SOURCE_NAME = "FortyGuard heatmap"

_USED_SNAPSHOTS_SQL = text(
    """
    WITH aoi AS (
        SELECT ST_SetSRID(ST_GeomFromGeoJSON(CAST(:aoi_geojson AS text)), 4326) AS geom
    ),
    used AS (
        SELECT DISTINCT bs.source_snapshot_id AS id
        FROM bus_stops bs, aoi
        WHERE ST_Intersects(bs.geom, aoi.geom)
        UNION
        SELECT DISTINCT t.source_snapshot_id AS id
        FROM svi_tracts t, aoi
        WHERE ST_Intersects(t.geom, aoi.geom)
    )
    SELECT s.source_name, s.source_url, s.source_version, s.retrieved_at,
           s.checksum, s.evidence_mode, s.license_note
    FROM source_snapshots s
    JOIN used ON used.id = s.id
    ORDER BY s.source_name
    """
)


def checksum_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


async def record_snapshot(
    session: AsyncSession,
    *,
    source_name: str,
    source_url: str,
    source_version: str,
    checksum: str,
    evidence_mode: str,
    license_note: str | None = None,
    retrieved_at: dt.datetime | None = None,
) -> SourceSnapshot:
    snapshot = SourceSnapshot(
        id=uuid.uuid4(),
        source_name=source_name,
        source_url=source_url,
        source_version=source_version,
        retrieved_at=retrieved_at or dt.datetime.now(dt.UTC),
        checksum=checksum,
        evidence_mode=evidence_mode,
        license_note=license_note,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def list_snapshots(session: AsyncSession) -> list[SourceSnapshot]:
    result = await session.execute(
        select(SourceSnapshot).order_by(SourceSnapshot.source_name, SourceSnapshot.retrieved_at.desc())
    )
    return list(result.scalars().all())


async def snapshots_used_for(
    session: AsyncSession, aoi_geojson: dict[str, Any]
) -> list[dict[str, Any]]:
    result = await session.execute(
        _USED_SNAPSHOTS_SQL, {"aoi_geojson": json.dumps(aoi_geojson)}
    )
    return [
        {
            "name": row["source_name"],
            "url": row["source_url"],
            "version": row["source_version"],
            "retrievedAt": row["retrieved_at"].isoformat(),
            "checksum": row["checksum"],
            "evidenceMode": row["evidence_mode"],
            "licenseNote": row["license_note"],
        }
        for row in result.mappings().all()
    ]


def heat_job_source_entry(job) -> dict[str, Any]:
    """Provenance for the heat layer itself, derived from the stored job."""
    mode = effective_runtime_mode(stored_mode=job.runtime_mode, reuse_count=job.reuse_count or 0)
    completed = job.completed_at.isoformat() if job.completed_at else None
    if mode is RuntimeMode.DEMO_FIXTURE:
        version = "Deterministic fixture, synthetic values shaped to the adapter contract"
    else:
        version = f"FortyGuard activity {job.provider_activity_id}"
    return {
        "name": FORTYGUARD_SOURCE_NAME,
        "url": "https://docs-api.fortyguard.com/docs/create-heatmap",
        "version": version,
        "retrievedAt": completed,
        "checksum": job.request_hash,
        "evidenceMode": mode.value,
        "licenseNote": None,
    }
