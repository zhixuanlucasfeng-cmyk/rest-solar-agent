from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def template(name: str) -> str:
    return (ROOT / "templates" / "admin" / name).read_text()


def test_admin_shell_exposes_role_country_and_primary_workspaces():
    base = template("base.html")
    assert "/static/admin.css" in base
    assert 'class="admin-shell"' in base
    assert 'class="admin-sidebar"' in base
    assert 'class="admin-main"' in base
    assert "admin-country" in base
    assert "current_user.role" in base
    assert "request.url.path" in base


def test_dashboard_is_action_led_and_inbox_preserves_safe_shortcut():
    dashboard = template("dashboard.html")
    inbox = template("inbox.html")
    assert "Open live inbox" in dashboard
    assert "Manage products" in dashboard
    assert "inbox-layout" in inbox
    assert "queue-item" in inbox
    assert "message-bubble" in inbox
    assert "Connection status" in inbox
    assert "Ctrl/⌘+Enter to send" in inbox
    assert "!event.isComposing" in inbox


def test_product_and_order_workspaces_use_operational_components():
    products = template("products.html")
    edit = template("product_edit.html")
    orders = template("orders.html")
    assert "ops-table" in products
    assert "record-form" in edit
    assert "Commercial" in edit
    assert "Specifications" in edit
    assert "Documents &amp; media" in edit
    assert "ops-table" in orders
    assert "status-label" in orders
