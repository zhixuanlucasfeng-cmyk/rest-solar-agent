from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaAsset


def media_url(asset_id: int | None, legacy_path: str | None) -> str | None:
    """URL for a media asset: the /media/{id} blob route if we have an asset id,
    else a single-leading-slash version of the legacy filesystem path, else None."""
    if asset_id is not None:
        return f"/media/{asset_id}"
    if legacy_path:
        return "/" + legacy_path.lstrip("/")
    return None


async def save_upload(db: AsyncSession, file: UploadFile, kind: str) -> int:
    """Store an uploaded file as a MediaAsset blob. Returns its id (after flush)."""
    data = await file.read()
    asset = MediaAsset(
        kind=kind,
        content_type=file.content_type or "application/octet-stream",
        data=data,
        filename=file.filename,
    )
    db.add(asset)
    await db.flush()
    return asset.id
