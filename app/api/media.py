from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import MediaAsset

router = APIRouter()


@router.get("/media/{asset_id}")
async def get_media(asset_id: int, db: AsyncSession = Depends(get_db)):
    asset = (
        await db.execute(select(MediaAsset).where(MediaAsset.id == asset_id))
    ).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=asset.data,
        media_type=asset.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
