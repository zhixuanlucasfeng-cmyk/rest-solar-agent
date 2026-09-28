import math

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import Product
from app.media import media_url
from app.countries import is_valid_country, normalize_country
from app.product_catalog import currency_for_country

router = APIRouter()


def _finite_price(price: float | None) -> float | None:
    return price if price is not None and math.isfinite(price) else None


def _public_media_url(request: Request, asset_id: int | None, legacy_path: str | None) -> str | None:
    if asset_id is not None:
        return str(request.url_for("get_media", asset_id=asset_id))
    relative_url = media_url(asset_id, legacy_path)
    if relative_url is None:
        return None
    return f"{str(request.base_url).rstrip('/')}{relative_url}"


@router.get("/api/products")
async def list_products(request: Request, country: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    """Public, read-only product feed for the country marketing sites.
    Excludes internal cost fields (duty_rate/vat_rate) — this is for display, not quoting.
    Public id and sku both identify the SKU; database_id exposes the numeric row id.

    Query parameters:
    - country: Optional country code (CM/NG/SD/ML). If provided and valid, returns shared products + country products.
               If invalid or not provided, returns only shared products (country=NULL).
    """
    stmt = (
        select(Product)
        .options(selectinload(Product.images))
        .where(Product.status == "active")
        .order_by(Product.category, Product.sku)
    )

    if country and is_valid_country(country):
        stmt = stmt.where(or_(Product.country.is_(None), Product.country == normalize_country(country)))
    else:
        stmt = stmt.where(Product.country.is_(None))

    result = await db.execute(stmt)
    products = result.scalars().all()
    return [
        {
            "id": p.sku,
            "database_id": p.id,
            "sku": p.sku,
            "country": normalize_country(p.country) if p.country else None,
            "status": p.status,
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
            "price_cny": _finite_price(p.price_cny),
            "price_xaf": _finite_price(p.price_xaf),
            "price_local": _finite_price(p.price_local) if p.country else None,
            "currency": currency_for_country(p.country),
            "stock": p.stock,
            "featured": p.featured,
            "features": p.features,
            "use_cases": p.use_cases,
            "image": _public_media_url(request, p.image_asset_id, p.image_path),
            "images": [_public_media_url(request, img.asset_id, img.path) for img in p.images],
            "datasheet": _public_media_url(request, p.datasheet_asset_id, p.datasheet_path),
        }
        for p in products
    ]
