from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.countries import normalize_country
from app.db.models import Product, ProductImage, ProductLocalization


_COPY_FIELDS = (
    "name", "price_cny", "price_xaf", "duty_rate", "vat_rate", "weight_kg",
    "category", "subcategory", "model", "wattage", "power_kw", "capacity_ah",
    "capacity_kwh", "voltage", "dimensions", "features", "datasheet_path",
    "image_path", "featured", "use_cases", "image_asset_id", "datasheet_asset_id",
)


def country_product_scope(country: str):
    """Products visible in one market, preferring its local copy over shared source."""
    country = normalize_country(country)
    has_local_copy = exists(
        select(ProductLocalization.id).where(
            ProductLocalization.source_product_id == Product.id,
            ProductLocalization.country == country,
        )
    )
    return or_(
        Product.country == country,
        and_(Product.country.is_(None), ~has_local_copy),
    )


async def localize_shared_product(
    db: AsyncSession, source: Product, country: str, *, status: str | None = None,
) -> Product:
    """Return the existing country copy, or clone a shared product for that market."""
    country = normalize_country(country)
    if source.country == country:
        return source
    if source.country is not None:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = await db.scalar(
        select(Product)
        .join(ProductLocalization, ProductLocalization.product_id == Product.id)
        .where(
            ProductLocalization.source_product_id == source.id,
            ProductLocalization.country == country,
        )
    )
    if existing is not None:
        if status is not None:
            existing.status = status
        return existing

    source = await db.scalar(
        select(Product).options(selectinload(Product.images)).where(Product.id == source.id)
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Product not found")

    sku = f"{source.sku[:47]}-{country}"
    if await db.scalar(select(Product.id).where(Product.sku == sku)) is not None:
        suffix = f"-{country}-{source.id}"
        sku = f"{source.sku[:50 - len(suffix)]}{suffix}"

    values = {field: getattr(source, field) for field in _COPY_FIELDS}
    country_copy = Product(
        **values,
        sku=sku,
        country=country,
        price_local=None,
        stock=0,
        status=status or source.status,
    )
    db.add(country_copy)
    await db.flush()
    db.add(ProductLocalization(
        source_product_id=source.id,
        product_id=country_copy.id,
        country=country,
    ))
    for image in source.images:
        db.add(ProductImage(
            product_id=country_copy.id,
            path=image.path,
            sort_order=image.sort_order,
            asset_id=image.asset_id,
        ))
    return country_copy
