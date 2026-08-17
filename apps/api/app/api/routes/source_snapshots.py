"""Source version and freshness metadata."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SourceSnapshotListResponse, SourceSnapshotResponse
from app.config import settings
from app.db.session import get_session
from app.domain.aoi import ALLOWED_AOI_GEOJSON, ALLOWED_AOI_NAME
from app.services import snapshots as service

router = APIRouter(prefix="/source-snapshots", tags=["source-snapshots"])


@router.get("", response_model=SourceSnapshotListResponse)
async def list_source_snapshots(
    session: AsyncSession = Depends(get_session),
) -> SourceSnapshotListResponse:
    """Expose the permitted source versions and the deployment's own limits.

    Everything here is public configuration: no credential, connection string,
    or provider key is included.
    """
    rows = await service.list_snapshots(session)
    return SourceSnapshotListResponse(
        snapshots=[
            SourceSnapshotResponse(
                id=row.id,
                source_name=row.source_name,
                source_url=row.source_url,
                source_version=row.source_version,
                retrieved_at=row.retrieved_at,
                checksum=row.checksum,
                evidence_mode=row.evidence_mode,
                license_note=row.license_note,
            )
            for row in rows
        ],
        live_provider_enabled=settings.live_provider_available,
        allowed_aoi=ALLOWED_AOI_GEOJSON,
        allowed_aoi_name=ALLOWED_AOI_NAME,
        allowed_date_min=settings.allowed_date_min,
        allowed_date_max=settings.allowed_date_max,
        max_aoi_area_km2=settings.max_aoi_area_km2,
        map_style_url=settings.map_style_url,
    )
