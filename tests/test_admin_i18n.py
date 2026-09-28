import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.admin.i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    admin_context,
    get_language,
    translate,
)
from app.admin.routes import templates
from app.media import media_url
from app.product_catalog import currency_for_country


def _request(cookie: str = "") -> Request:
    return Request({"type": "http", "headers": [(b"cookie", cookie.encode())]})


def test_supported_languages_and_unknown_cookie_default_to_english():
    assert SUPPORTED_LANGUAGES == ("en", "zh", "fr")
    assert DEFAULT_LANGUAGE == "en"
    assert get_language(_request("admin_lang=zh")) == "zh"
    assert get_language(_request("admin_lang=xx")) == "en"
    assert get_language(_request()) == "en"


def test_catalog_keys_match_and_interpolation_works():
    assert set(TRANSLATIONS) == {"en", "zh", "fr"}
    assert set(TRANSLATIONS["en"]) == set(TRANSLATIONS["zh"]) == set(TRANSLATIONS["fr"])
    assert translate("en", "products_count", count=3) == "3 products"
    assert translate("zh", "products_count", count=3) == "3 个产品"
    assert translate("fr", "products_count", count=3) == "3 produits"
    assert translate("xx", "products") == "Products"


@pytest.mark.parametrize("language,expected", [
    ("en", ("country_admin", "superadmin", "agent")),
    ("zh", ("国家管理员", "超级管理员", "客服")),
    ("fr", ("Administrateur national", "Superadministrateur", "Agent")),
])
def test_role_labels_are_translated(language, expected):
    assert tuple(translate(language, role) for role in ("country_admin", "superadmin", "agent")) == expected


def test_context_renders_translated_product_label_and_preserves_globals():
    context = admin_context(_request("admin_lang=zh"))
    assert context["lang"] == "zh"
    assert context["supported_languages"] == SUPPORTED_LANGUAGES
    assert templates.env.from_string("{{ t('products') }}").render(**context) == "产品"
    assert templates.env.globals["media_url"] is media_url
    assert templates.env.globals["currency_for_country"] is currency_for_country


@pytest.mark.asyncio
async def test_language_route_persists_cookie_and_redirects_locally():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/language",
            data={"language": "zh", "next": "/admin/products"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/products"
        cookie = response.headers["set-cookie"]
        assert "admin_lang=zh" in cookie
        assert "Max-Age=31536000" in cookie
        assert "SameSite=lax" in cookie
        assert get_language(_request(f"admin_lang={client.cookies['admin_lang']}")) == "zh"


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [
    "/admin/products/12/edit", "/admin/dashboard", "/admin/products",
])
async def test_language_route_accepts_other_local_admin_targets(target):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/language", data={"language": "fr", "next": target},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == target


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [
    "https://evil.example", "https://[evil", "//evil.example", "/other",
    "/admin/../outside", "/admin/%2e%2e/outside", "/admin/%252e%252e/outside",
    "/admin/%3F/%2e%2e/%2e%2e/outside", "/admin/%70roducts",
    "/admin/\\evil.example", "/admin/%255c/evil.example",
    "/admin/products?status=active", "/admin/products#top", "/admin/产品",
])
async def test_language_route_rejects_unsafe_next(target):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/language", data={"language": "invalid", "next": target},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/dashboard"
    assert "admin_lang=en" in response.headers["set-cookie"]
