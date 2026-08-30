from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import Product
from app.media import media_url

router = APIRouter()


@router.get("/api/products")
async def list_products(db: AsyncSession = Depends(get_db)):
    """Public, read-only product feed for the country marketing sites.
    Excludes internal cost fields (duty_rate/vat_rate) — this is for display, not quoting.
    """
    result = await db.execute(
        select(Product).options(selectinload(Product.images)).order_by(Product.category, Product.sku)
    )
    products = result.scalars().all()
    return [
        {
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "subcategory": p.subcategory,
            "model": p.model,
            "wattage": p.wattage,
            "power_kw": p.power_kw,
            "capacity_ah": p.capacity_ah,
            "capacity_kwh": p.capacity_kwh,
            "voltage": p.voltage,
            "dimensions": p.dimensions,
            "price_cny": p.price_cny,
            "price_xaf": p.price_xaf,
            "featured": p.featured,
            "features": p.features,
            "use_cases": p.use_cases,
            "image": media_url(p.image_asset_id, p.image_path),
            "images": [media_url(img.asset_id, img.path) for img in p.images],
            "datasheet": media_url(p.datasheet_asset_id, p.datasheet_path),
        }
        for p in products
    ]
