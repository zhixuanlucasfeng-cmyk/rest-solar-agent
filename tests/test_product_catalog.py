import pytest
from fastapi import HTTPException

from app.product_catalog import (
    COUNTRY_CURRENCIES,
    PRODUCT_STATUSES,
    currency_for_country,
    validate_product_values,
)


def test_country_currency_map_is_complete():
    assert COUNTRY_CURRENCIES == {
        "CM": "XAF", "ML": "XOF", "NG": "NGN", "SD": "SDG",
    }
    assert currency_for_country("ng") == "NGN"
    assert currency_for_country(None) is None


def test_product_statuses_are_stable():
    assert PRODUCT_STATUSES == ("active", "inactive", "archived")


@pytest.mark.parametrize(
    ("status", "price_local", "price_cny", "stock"),
    [
        ("unknown", None, None, 0),
        ("active", -1, None, 0),
        ("active", None, -1, 0),
        ("active", None, None, -1),
    ],
)
def test_invalid_product_values_raise_400(status, price_local, price_cny, stock):
    with pytest.raises(HTTPException) as exc:
        validate_product_values(
            status=status, price_local=price_local, price_cny=price_cny, stock=stock,
        )
    assert exc.value.status_code == 400


def test_valid_product_values_are_accepted():
    validate_product_values(status="archived", price_local=0, price_cny=0, stock=0)
    validate_product_values(status="active", price_local=None, price_cny=None, stock=5)
