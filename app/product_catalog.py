import math

from fastapi import HTTPException

PRODUCT_STATUSES = ("active", "inactive", "archived")
COUNTRY_CURRENCIES = {
    "CM": "XAF",
    "ML": "XOF",
    "NG": "NGN",
    "SD": "SDG",
}


def currency_for_country(country: str | None) -> str | None:
    return COUNTRY_CURRENCIES.get(country.upper()) if country else None


def validate_product_values(
    *, status: str, price_local: float | None, price_cny: float | None, stock: int,
) -> None:
    if status not in PRODUCT_STATUSES:
        raise HTTPException(status_code=400, detail="invalid_product_status")
    for price in (price_local, price_cny):
        if price is not None and (not math.isfinite(price) or price < 0):
            raise HTTPException(status_code=400, detail="invalid_product_price")
    if stock < 0:
        raise HTTPException(status_code=400, detail="invalid_product_stock")
