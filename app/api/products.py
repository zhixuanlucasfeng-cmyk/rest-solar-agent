from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import Product
from app.media import media_url
from app.countries import is_valid_country, normalize_country

router = APIRouter()


@router.get("/api/products")
async def list_products(country: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    """Public, read-only product feed for the country marketing sites.
    Excludes internal cost fields (duty_rate/vat_rate) — this is for display, not quoting.

    Query parameters:
    - country: Optional country code (CM/NG/SD/ML). If provided and valid, returns shared products + country products.
               If invalid or not provided, returns only shared products (country=NULL).
    """
    stmt = select(Product).options(selectinload(Product.images)).order_by(Product.category, Product.sku)

    if country and is_valid_country(country):
        stmt = stmt.where(or_(Product.country.is_(None), Product.country == normalize_country(country)))
    else:
        stmt = stmt.where(Product.country.is_(None))

    result = await db.execute(stmt)
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
