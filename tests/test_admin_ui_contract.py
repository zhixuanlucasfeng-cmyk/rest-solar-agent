from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request

from app.admin.i18n import admin_context, translate
from app.admin.routes import templates
from app.db.models import Product


ROOT = Path(__file__).resolve().parents[1]


def template(name: str) -> str:
    return (ROOT / "templates" / "admin" / name).read_text()


def rendered_template(name: str, language: str) -> str:
    request = Request({
        "type": "http", "scheme": "https", "server": ("test", 443),
        "path": f"/admin/{name.removesuffix('.html')}", "query_string": b"",
        "headers": [(b"cookie", f"admin_lang={language}".encode())],
    })
    return templates.get_template(f"admin/{name}").render(
        request=request, current_user=SimpleNamespace(id=1, role="superadmin", country="NG"),
        p=Product(name="Panel", sku="PANEL", country="NG", status="active"),
        product_statuses=("active", "inactive", "archived"),
        **admin_context(request),
    )


def test_admin_shell_exposes_role_country_and_primary_workspaces():
    base = template("base.html")
    assert "/static/admin.css" in base
    assert 'class="admin-shell"' in base
    assert 'class="admin-sidebar"' in base
    assert 'class="admin-main"' in base
    assert "admin-country" in base
    assert "current_user.role" in base
    assert "request.url.path" in base


@pytest.mark.parametrize("language", ["en", "zh", "fr"])
def test_dashboard_is_action_led_and_inbox_preserves_safe_shortcut(language):
    dashboard = rendered_template("dashboard.html", language)
    inbox = rendered_template("inbox.html", language)
    assert translate(language, "open_live_inbox") in dashboard
    assert translate(language, "manage_products") in dashboard
    assert "inbox-layout" in inbox
    assert "queue-item" in inbox
    assert "message-bubble" in inbox
    assert translate(language, "connection_connecting") in inbox
    assert translate(language, "reply_shortcut") in inbox
    assert "!event.isComposing" in inbox


@pytest.mark.parametrize("language", ["en", "zh", "fr"])
def test_product_and_order_workspaces_use_operational_components(language):
    products = template("products.html")
    edit = rendered_template("product_edit.html", language)
    orders = template("orders.html")
    assert "ops-table" in products
    assert "record-form" in edit
    from markupsafe import escape

    for key in ("commercial", "specifications", "documents_media"):
        assert escape(translate(language, key)) in edit
    assert "ops-table" in orders
    assert "status-label" in orders
