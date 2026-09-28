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
from app.admin.auth import create_access_token, hash_password
from app.db.models import AdminUser, Base, Conversation, Message, Order, Product, Ticket
from app.db.session import get_db
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def translated_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        user = AdminUser(email="translation@test.com", password_hash=hash_password("pass"), role="superadmin")
        conversation = Conversation(session_id="original-session", country="NG")
        session.add_all([user, conversation])
        await session.flush()
        session.add_all([
            Product(name="Original Panel 原文", sku="ORIGINAL-1", country="NG", status="active"),
            Message(conversation_id=conversation.id, role="user", content="Please keep this message 原文 unchanged."),
            Order(order_number="ORIGINAL-ORDER", customer_name="Original Customer 原文", items="Original Panel 原文", country="NG"),
            Ticket(subject="Original subject 原文", body="Original body", conversation_id=conversation.id),
        ])
        await session.commit()
        token = create_access_token({"sub": str(user.id), "role": user.role})

    async def database():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = database
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies={"admin_token": token}) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "fr"])
async def test_admin_pages_translate_navigation_headings_and_preserve_content(translated_client, language):
    import html
    import re

    translated_client.cookies.set("admin_lang", language)
    for page, heading in [
        ("dashboard", "dashboard"), ("products", "products"), ("orders", "orders"),
        ("inbox", "live_inbox"), ("users", "admin_users"), ("reports", "reports"),
        ("conversations", "conversations"), ("tickets", "tickets"), ("rules", "rules"),
        ("products/1/edit", "edit_product"),
    ]:
        response = await translated_client.get(f"/admin/{page}?ignored=1")
        assert response.status_code == 200
        text = html.unescape(response.text)
        assert f'<html lang="{language}">' in text
        assert re.search(r'<h1[^>]*>' + re.escape(translate(language, heading)), text)
        assert f'>{translate(language, "logout")}</button>' in text
        assert 'action="/admin/language" method="post"' in text
        assert f'name="next" value="/admin/{page}"' in text
        assert 'value="zh"' in text and 'value="fr"' in text and 'value="en"' in text
        if page in ("products", "products/1/edit", "orders"):
            assert "Original Panel 原文" in text
        if page == "products":
            assert translate(language, "unpublish") in text
            assert translate(language, "active") in text
            assert translate(language, "inactive") in text
            assert translate(language, "archived") in text
        if page == "orders":
            assert "Original Customer 原文" in text and "ORIGINAL-ORDER" in text
            assert f'>{translate(language, "pending")}</span>' in text
        if page == "tickets":
            assert "Original subject 原文" in text
            assert translate(language, "close") in text
    detail = await translated_client.get("/admin/conversations/1")
    assert detail.status_code == 200
    assert "Please keep this message 原文 unchanged." in detail.text
    assert translate(language, "conversation_number", id=1) in html.unescape(detail.text)
    messages = await translated_client.get("/admin/conversations/1/messages")
    assert any(m["content"] == "Please keep this message 原文 unchanged." for m in messages.json())


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "fr"])
async def test_login_translates_fields_selector_and_authentication_error(translated_client, language):
    import html

    translated_client.cookies.clear()
    translated_client.cookies.set("admin_lang", language)
    response = await translated_client.get("/admin/login")
    assert response.status_code == 200
    text = html.unescape(response.text)
    assert f'<html lang="{language}">' in text
    assert 'action="/admin/language" method="post"' in text
    assert 'name="next" value="/admin/login"' in text
    for key in ("language", "login"):
        assert translate(language, key) in text
    for key in ("email", "password"):
        assert f'placeholder="{translate(language, key)}"' in text
    invalid = await translated_client.post("/admin/login", data={"email": "translation@test.com", "password": "wrong"})
    assert translate(language, "invalid_credentials") in html.unescape(invalid.text)
    assert "Invalid email or password" not in invalid.text


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh", "fr"])
async def test_translated_delete_prompt_keeps_product_text_out_of_script(translated_client, language):
    import html
    import json
    import re

    translated_client.cookies.set("admin_lang", language)
    name = 'Panel "</script><img src=x onerror=alert(1)> O\'Brien `${alert(1)}` $& 原文'
    created = await translated_client.post("/admin/products", data={"name": name, "sku": "ESCAPE-1"})
    assert created.status_code == 302
    response = await translated_client.get("/admin/products")
    assert response.status_code == 200
    labels = re.findall(r'data-delete-product="([^"]+)"', response.text)
    assert f"{name} (ESCAPE-1)" in [html.unescape(label) for label in labels]
    script = re.findall(r'<script>(.*?)</script>', response.text, re.S)[-1]
    assert "ESCAPE-1" not in script and "onerror=" not in script
    confirmation = re.search(r'const confirmation = (.*);', script).group(1)
    assert json.loads(confirmation) == translate(language, "delete_product_confirmation", product="{product}")


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
