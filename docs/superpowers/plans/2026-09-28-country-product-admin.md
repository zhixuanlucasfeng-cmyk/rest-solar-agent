# Country Product Administration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let each country manager safely manage that country's website products, prices, stock, images, and publication lifecycle from an English/Chinese/French admin UI, while keeping public website catalogs synchronized with the backend.

**Architecture:** The FastAPI service remains the source of truth. Add a reversible lifecycle and country-local price to `Product`, apply an idempotent startup schema upgrade for existing Neon data, enforce country scope in admin routes, and publish only active products through the public API and Gemini catalog tools. The marketing site consumes the same public API on both the homepage and Products page, falling back to bundled data only when the API cannot be reached.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, PostgreSQL/Neon, SQLite tests, Jinja2, Tailwind CDN, vanilla JavaScript, Node's built-in test runner, pytest/httpx.

**Spec:** `docs/superpowers/specs/2026-09-27-country-product-admin-design.md`

## Global Constraints

- Country codes and currencies are fixed: `CM → XAF`, `ML → XOF`, `NG → NGN`, `SD → SDG`.
- Product states are fixed: `active`, `inactive`, `archived`.
- Existing and newly created products default to `active`.
- Only `active` products appear in the public API, Gemini catalog context, or quoting lookup.
- Country administrators can create and modify only products owned by their country. Shared products remain read-only to them.
- Country administrators can switch owned products among all three states, but cannot permanently delete products.
- Only the superadmin can permanently delete a product.
- `price_local` and `price_cny` are nullable and must be non-negative when present; `stock` must be non-negative.
- Preserve existing `price_xaf` for compatibility. During schema upgrade, copy it into `price_local` only for Cameroon rows whose `price_local` is null.
- A successful empty API response is authoritative. Static website data is used only after network, non-2xx, or malformed-payload failure.
- Dynamic business data such as product names, SKUs, customer messages, and order notes is never machine-translated by the admin UI.
- Do not change the current public page visual design in this delivery; only connect catalog data and render backend prices/stock.

---

### Task 1: Add product lifecycle and currency domain rules

**Files:**
- Create: `app/product_catalog.py`
- Modify: `app/db/models.py`
- Test: `tests/test_product_catalog.py`

**Step 1: Write failing domain tests**

Create `tests/test_product_catalog.py`:

```python
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
```

**Step 2: Run the focused test and confirm RED**

Run: `pytest -q tests/test_product_catalog.py`

Expected: import failure for `app.product_catalog`.

**Step 3: Implement the domain module and model fields**

Create `app/product_catalog.py`:

```python
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
        raise HTTPException(status_code=400, detail="Invalid product status")
    if price_local is not None and price_local < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    if price_cny is not None and price_cny < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    if stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
```

In `app/db/models.py`, add to `Product` beside the current price and country fields:

```python
price_local: Mapped[float | None] = mapped_column(Float, nullable=True)
status: Mapped[str] = mapped_column(
    String(20), nullable=False, default="active", server_default="active", index=True,
)
```

Do not remove `price_cny` or `price_xaf`.

**Step 4: Run focused tests and confirm GREEN**

Run: `pytest -q tests/test_product_catalog.py tests/test_models.py`

Expected: all pass.

**Step 5: Commit**

```bash
git add app/product_catalog.py app/db/models.py tests/test_product_catalog.py
git commit -m "feat: add product lifecycle and local pricing domain"
```

---

### Task 2: Upgrade existing SQLite and Neon product tables safely

**Files:**
- Create: `app/db/schema.py`
- Modify: `app/main.py`
- Test: `tests/test_schema_upgrade.py`

**Step 1: Write failing migration tests**

Create a file-backed SQLite database with a legacy `products` table containing `id`, `country`, and `price_xaf`; call `upgrade_schema`; use SQLAlchemy inspection to assert that `price_local` and `status` exist. Seed three rows and assert:

```python
assert rows == [
    ("CM", 125000.0, "active"),
    ("NG", None, "active"),
    (None, None, "active"),
]
```

Call `upgrade_schema` a second time and assert it is idempotent. Also test a fresh database created from the current ORM metadata.

**Step 2: Run and confirm RED**

Run: `pytest -q tests/test_schema_upgrade.py`

Expected: import failure for `app.db.schema`.

**Step 3: Implement an additive, dialect-aware upgrade**

Create `app/db/schema.py` with:

```python
from sqlalchemy import inspect, text


def upgrade_schema(connection) -> None:
    inspector = inspect(connection)
    if "products" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("products")}
    dialect = connection.dialect.name

    if "price_local" not in columns:
        connection.execute(text("ALTER TABLE products ADD COLUMN price_local FLOAT"))
    if "status" not in columns:
        default = "DEFAULT 'active'" if dialect == "sqlite" else "DEFAULT 'active'"
        connection.execute(text(
            f"ALTER TABLE products ADD COLUMN status VARCHAR(20) NOT NULL {default}"
        ))

    connection.execute(text(
        "UPDATE products SET status = 'active' WHERE status IS NULL OR status = ''"
    ))
    connection.execute(text(
        "UPDATE products SET price_local = price_xaf "
        "WHERE country = 'CM' AND price_local IS NULL AND price_xaf IS NOT NULL"
    ))
```

Do not add a separate index in this release; avoiding duplicate-index edge cases makes the upgrade safely repeatable. In `app/main.py`, invoke it immediately after ORM table creation:

```python
async with engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
    await conn.run_sync(upgrade_schema)
```

Import `upgrade_schema` from `app.db.schema`.

**Step 4: Run migration and startup tests**

Run: `pytest -q tests/test_schema_upgrade.py tests/test_render_config.py tests/test_seed_admins.py`

Expected: all pass.

**Step 5: Commit**

```bash
git add app/db/schema.py app/main.py tests/test_schema_upgrade.py
git commit -m "feat: upgrade existing product schema safely"
```

---

### Task 3: Publish only active products and expose local catalog fields

**Files:**
- Modify: `app/api/products.py`
- Modify: `app/agent/orchestrator.py`
- Modify: `app/tools/__init__.py`
- Modify: `app/tools/quote.py`
- Modify: `tests/test_products_api.py`
- Modify: `tests/test_orchestrator.py`
- Create: `tests/test_ai_price_safety.py`
- Modify: `tests/test_quote_tool.py`

**Step 1: Add failing public API tests**

Add active, inactive, and archived products for the same country. Assert the API returns only the active SKU and includes:

```python
{
    "id": active.id,
    "country": "NG",
    "status": "active",
    "price_local": 850000.0,
    "currency": "NGN",
    "stock": 7,
}
```

Keep the existing invalid/missing-country shared-product assertions.

**Step 2: Add failing Gemini/quote visibility and price-safety tests**

In `tests/test_orchestrator.py`, verify `_retrieve_catalog_context` contains the active SKU and excludes inactive and archived SKUs. In `tests/test_quote_tool.py`, verify direct quote lookup rejects or returns no product for a non-active SKU.

Create `tests/test_ai_price_safety.py` and assert that:

- `get_tools(db)` does not expose a tool named `get_quote` to Gemini;
- `_retrieve_catalog_context` contains “Price must be confirmed with staff” but not the numeric `price_local`, `price_xaf`, `NGN`, or `FCFA` value;
- `_SYSTEM_TEMPLATE` says prices change and exact prices must be confirmed by human staff, and no longer contains the current instruction to state prices naturally.

**Step 3: Run focused tests and confirm RED**

Run: `pytest -q tests/test_products_api.py tests/test_orchestrator.py tests/test_quote_tool.py tests/test_ai_price_safety.py`

Expected: inactive rows leak and new response keys are absent.

**Step 4: Apply the active filter at every product read boundary**

In `app/api/products.py`, add `Product.status == "active"` to the query before country scope and serialize `id`, `country`, `status`, `price_local`, `currency_for_country(p.country)`, and `stock`. Preserve existing response keys for compatibility.

In `app/agent/orchestrator.py::_retrieve_catalog_context`, add `Product.status == "active"` to its select query.

In `app/tools/quote.py`, add `Product.status == "active"` to every SKU/product selection used for customer quotes.

The assistant must not turn mutable catalog prices into promises:

- In `app/tools/__init__.py`, remove `QuoteTool(db)` from `get_tools`; retain the module and its direct unit tests for internal compatibility, but do not expose it to Gemini.
- In `_retrieve_catalog_context`, replace the numeric `price_bit` with exactly `Price must be confirmed with staff because local prices can change.`
- In `_SYSTEM_TEMPLATE`, replace the current price example with: `- Prices can change. Never state or promise an exact price. Ask the customer to check the product page and confirm the current price with human staff.`
- Do not remove public website prices; this restriction applies to AI replies, not the managed catalog UI.

**Step 5: Run focused tests and confirm GREEN**

Run: `pytest -q tests/test_products_api.py tests/test_orchestrator.py tests/test_quote_tool.py tests/test_ai_price_safety.py`

Expected: all pass.

**Step 6: Commit**

```bash
git add app/api/products.py app/agent/orchestrator.py app/tools/__init__.py app/tools/quote.py tests/test_products_api.py tests/test_orchestrator.py tests/test_quote_tool.py tests/test_ai_price_safety.py
git commit -m "feat: publish active catalog with AI price safety"
```

---

### Task 4: Enforce product lifecycle, pricing, and deletion permissions

**Files:**
- Modify: `app/admin/routes.py`
- Modify: `tests/test_admin_routes.py`
- Modify: `tests/test_admin_scope.py`

**Step 1: Add reusable country-admin fixtures and failing permission tests**

Cover these observable cases through HTTP:

- A Nigeria country admin creates a product while posting `country=CM`; the stored country is still `NG`.
- The same admin edits its name, `price_local`, stock, and image.
- The same admin changes its status from active to inactive, then archived, then active.
- Negative local price and negative stock return 400 and do not persist.
- Invalid status returns 400.
- Missing product ID returns 404 on status change and permanent delete.
- A country admin receives 403 when editing/changing a shared product.
- A country admin receives 404 when editing/changing another country's product.
- A country admin receives 403 from `POST /admin/products/{id}/delete`.
- A superadmin can permanently delete a product.

**Step 2: Run focused tests and confirm RED**

Run: `pytest -q tests/test_admin_routes.py tests/test_admin_scope.py`

Expected: status endpoint absent; country admin can currently delete.

**Step 3: Extend form parsing and create/update routes**

Change `_product_fields_from_form` to accept `price_local` and `status`, call `validate_product_values`, and include both fields in the returned dictionary. Extend create/update form parameters:

```python
price_local: float | None = Form(None),
status: str = Form("active"),
```

Continue accepting legacy `price_cny` and `price_xaf`. For country administrators ignore submitted country and set `current_user.country`. For superadmin, normalize a submitted country and reject unknown non-empty values with HTTP 400.

**Step 4: Add the lifecycle endpoint**

Implement:

```python
@router.post("/products/{product_id}/status")
async def update_product_status(
    product_id: int,
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
):
    validate_product_values(status=status, price_local=None, price_cny=None, stock=0)
    product = await db.scalar(select(Product).where(Product.id == product_id))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    _assert_product_writable(current_user, product)
    product.status = status
    await db.commit()
    return RedirectResponse(url=f"/admin/products?status={status}", status_code=302)
```

**Step 5: Restrict permanent deletion**

Change the delete route dependency to `require_superadmin`. Return 404 if the product does not exist; otherwise delete and commit. Do not silently succeed on missing IDs.

**Step 6: Add list filtering**

Add `status: str = "active"` to the Products page. Reject unsupported non-empty values with 400. Apply the status filter to the visible query and calculate separate state counts within the same country scope. Pass `selected_status`, `status_counts`, and `product_statuses` to the template.

**Step 7: Run focused tests and confirm GREEN**

Run: `pytest -q tests/test_admin_routes.py tests/test_admin_scope.py`

Expected: all pass.

**Step 8: Commit**

```bash
git add app/admin/routes.py tests/test_admin_routes.py tests/test_admin_scope.py
git commit -m "feat: enforce country product lifecycle permissions"
```

---

### Task 5: Build the manager product workflow in the admin templates

**Files:**
- Modify: `templates/admin/products.html`
- Modify: `templates/admin/product_edit.html`
- Modify: `tests/test_admin_routes.py`

**Step 1: Add failing rendered-page tests**

Assert that the products page for a country admin contains:

- the correct currency label for its country;
- status tabs for active, inactive, and archived;
- `Unpublish` for active owned products;
- `Archive` for inactive owned products;
- `Restore` for archived owned products;
- no permanent-delete control.

Assert that the superadmin page includes permanent delete only for superadmin.

**Step 2: Run the focused rendered-page tests and confirm RED**

Run: `pytest -q tests/test_admin_routes.py -k product`

Expected: lifecycle controls and local currency are absent.

**Step 3: Update list and edit templates**

- Replace the create form's XAF-only sales input with `price_local`, labelled using `currency_for_country(current_user.country)` for country admins and a generic local-price label for shared/superadmin editing.
- Keep CNY in the edit form as an internal compatibility field; do not make XAF the visible local price for all countries.
- Add status tabs that preserve category filters.
- Render state badges.
- Use one POST form to `/status` with `inactive` for “Unpublish”, `archived` for “Archive”, and `active` for “Restore”.
- Display the delete form only when `current_user.role == "superadmin"`.
- Keep shared products read-only to country admins.
- Add a status select to the edit page and submit it with the normal edit form.
- Make the table horizontally scrollable on narrow screens and keep action buttons at least 40px high.

Pass `currency_for_country` into template globals in `app/admin/routes.py` so the display logic stays out of Jinja.

**Step 4: Run tests and inspect HTML**

Run: `pytest -q tests/test_admin_routes.py -k product`

Expected: all product UI tests pass.

**Step 5: Commit**

```bash
git add app/admin/routes.py templates/admin/products.html templates/admin/product_edit.html tests/test_admin_routes.py
git commit -m "feat: add safe product publishing workflow"
```

---

### Task 6: Add English, Chinese, and French admin localization infrastructure

**Files:**
- Create: `app/admin/i18n.py`
- Modify: `app/admin/routes.py`
- Test: `tests/test_admin_i18n.py`

**Step 1: Write failing unit and route tests**

Test:

- supported languages equal `("en", "zh", "fr")`;
- unknown language falls back to English;
- every language dictionary has exactly the same keys;
- interpolation works for strings such as `products_count`;
- `POST /admin/language` stores `admin_lang=zh` and redirects to a safe `/admin/...` path;
- an external `next=https://evil.example` is replaced with `/admin/dashboard`;
- the cookie persists and changes rendered product labels.

**Step 2: Run and confirm RED**

Run: `pytest -q tests/test_admin_i18n.py`

Expected: `app.admin.i18n` and language route are absent.

**Step 3: Implement the translation catalog**

Create `app/admin/i18n.py` with `SUPPORTED_LANGUAGES`, `DEFAULT_LANGUAGE`, `TRANSLATIONS`, `get_language(request)`, `translate(language, key, **values)`, and `admin_context(request)`.

Use stable semantic keys. The catalog must include, at minimum, the following exact translations:

| Key | English | 中文 | Français |
|---|---|---|---|
| `brand_admin` | RestarSolar Admin | RestarSolar 管理后台 | Administration RestarSolar |
| `language` | Language | 语言 | Langue |
| `dashboard` | Dashboard | 控制台 | Tableau de bord |
| `inbox` | Inbox | 收件箱 | Boîte de réception |
| `conversations` | Conversations | 对话 | Conversations |
| `products` | Products | 产品 | Produits |
| `orders` | Orders | 订单 | Commandes |
| `tickets` | Tickets | 工单 | Tickets |
| `reports` | Reports | 报表 | Rapports |
| `rules` | Rules | 规则 | Règles |
| `users` | Users | 用户 | Utilisateurs |
| `logout` | Logout | 退出登录 | Déconnexion |
| `login` | Sign in | 登录 | Se connecter |
| `email` | Email | 邮箱 | E-mail |
| `password` | Password | 密码 | Mot de passe |
| `name` | Name | 名称 | Nom |
| `country` | Country | 国家 | Pays |
| `category` | Category | 分类 | Catégorie |
| `price` | Price | 价格 | Prix |
| `local_price` | Local price | 当地价格 | Prix local |
| `stock` | Stock | 库存 | Stock |
| `status` | Status | 状态 | Statut |
| `active` | Active | 已上架 | Actif |
| `inactive` | Unpublished | 已下架 | Non publié |
| `archived` | Archived | 已归档 | Archivé |
| `unpublish` | Unpublish | 下架 | Retirer |
| `archive` | Archive | 归档 | Archiver |
| `restore` | Restore | 恢复上架 | Restaurer |
| `edit` | Edit | 编辑 | Modifier |
| `delete_permanently` | Delete permanently | 永久删除 | Supprimer définitivement |
| `add_product` | Add product | 添加产品 | Ajouter un produit |
| `save_changes` | Save changes | 保存更改 | Enregistrer les modifications |
| `on_request` | On request | 询价 | Sur demande |
| `shared_all_countries` | Shared (all countries) | 共享（所有国家） | Partagé (tous les pays) |
| `read_only` | Read-only | 只读 | Lecture seule |
| `back_to_products` | Back to products | 返回产品列表 | Retour aux produits |

Add the remaining static strings found in all admin templates to the same catalog before Task 7; the exact-key-set test prevents missing language variants.

**Step 4: Wire a context processor and language route**

Instantiate templates with `context_processors=[admin_context]`. The processor returns:

```python
{
    "lang": language,
    "supported_languages": SUPPORTED_LANGUAGES,
    "t": lambda key, **values: translate(language, key, **values),
}
```

Add:

```python
@router.post("/language")
async def set_admin_language(
    language: str = Form(...), next: str = Form("/admin/dashboard")
):
    chosen = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    target = next if next.startswith("/admin/") and not next.startswith("//") else "/admin/dashboard"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie("admin_lang", chosen, max_age=31536000, samesite="lax")
    return response
```

**Step 5: Run tests and confirm GREEN**

Run: `pytest -q tests/test_admin_i18n.py`

Expected: all pass.

**Step 6: Commit**

```bash
git add app/admin/i18n.py app/admin/routes.py tests/test_admin_i18n.py
git commit -m "feat: add trilingual admin localization"
```

---

### Task 7: Translate every admin page and make the language selector global

**Files:**
- Modify: `templates/admin/base.html`
- Modify: `templates/admin/login.html`
- Modify: `templates/admin/dashboard.html`
- Modify: `templates/admin/inbox.html`
- Modify: `templates/admin/conversations.html`
- Modify: `templates/admin/conversation_detail.html`
- Modify: `templates/admin/products.html`
- Modify: `templates/admin/product_edit.html`
- Modify: `templates/admin/orders.html`
- Modify: `templates/admin/tickets.html`
- Modify: `templates/admin/rules.html`
- Modify: `templates/admin/users.html`
- Modify: `templates/admin/reports.html`
- Modify: `app/admin/i18n.py`
- Modify: `tests/test_admin_i18n.py`

**Step 1: Add failing representative page tests**

For authenticated admin requests with `admin_lang=zh` and `admin_lang=fr`, render dashboard, products, orders, inbox, users, and reports. Assert translated navigation and page headings, while seeded product names and customer messages remain byte-for-byte unchanged. Render login without authentication and assert its language selector and translated fields.

**Step 2: Run and confirm RED**

Run: `pytest -q tests/test_admin_i18n.py`

Expected: templates still contain English literals.

**Step 3: Replace static UI text with `t(...)`**

In `base.html`, set `<html lang="{{ lang }}">` and add a compact POST language selector in the global header. Its hidden `next` field is `request.url.path`, so the user stays on the same admin page. Use the same selector on `login.html` outside the authenticated navigation.

Translate all headings, labels, buttons, table headers, empty states, status captions, image/upload instructions, confirmation prompts, and navigation items in the listed templates. Leave product/customer/order content unchanged. Translate backend login error by sending an error key (`invalid_credentials`) rather than raw English text.

**Step 4: Run i18n and admin suites**

Run: `pytest -q tests/test_admin_i18n.py tests/test_admin_routes.py tests/test_admin_auth.py tests/test_admin_scope.py`

Expected: all pass.

**Step 5: Commit**

```bash
git add app/admin/i18n.py app/admin/routes.py templates/admin tests/test_admin_i18n.py
git commit -m "feat: translate admin interface into three languages"
```

---

### Task 8: Adapt website catalog prices and stock to the new API

**Repository:** `/Users/lucasfeng/Documents/ChatGPT/restar app/camaroom-web-proof-led-redesign`

**Files:**
- Modify: `assets/js/catalog.js`
- Modify: `index.html`
- Modify: `test/catalog.test.js`
- Create: `test/homepage-currency.test.js`

**Step 1: Add failing adapter tests**

Extend the API fixture with `price_local`, `currency`, and `status`. Assert:

```javascript
assert.equal(ng.product.price, 850000);
assert.equal(ng.product.currency, "NGN");
assert.equal(ng.inventory, 7);
assert.equal(cm.product.currency, "XAF");
```

Also assert shared legacy rows with no `price_local` still render without inventing a price, and successful empty responses still replace fallback data.

**Step 2: Run and confirm RED**

Run: `node --test test/catalog.test.js`

Expected: non-Cameroon local price/currency assertions fail.

**Step 3: Update the adapter**

In `adaptProduct`, prefer API-native local fields:

```javascript
const localPrice = finiteNumber(row.price_local);
const currency = typeof row.currency === "string" ? row.currency : null;
```

Return `price: localPrice`, `currency`, and `stock`. Keep the existing Cameroon `price_xaf` conversion only as compatibility fallback when `price_local` is absent and the requested country is CM. Do not synthesize prices for NG, SD, or ML.

In `index.html`, replace both hard-coded `FCFA` render points with the adapted product currency, escaped before HTML interpolation. Fall back to the selected country's configured currency only when an old bundled product has a price but no currency. Change the three localized product subtitles so they say that prices use the selected country's local currency instead of claiming every country uses XAF. Add `test/homepage-currency.test.js` to assert the grid and modal use `p.currency`/country currency and no price-rendering path hard-codes `FCFA`.

**Step 4: Run catalog tests and confirm GREEN**

Run: `node --test test/catalog.test.js test/homepage-currency.test.js`

Expected: all pass.

**Step 5: Commit in the website repository**

```bash
git add assets/js/catalog.js index.html test/catalog.test.js test/homepage-currency.test.js
git commit -m "feat: consume country-local product prices"
```

---

### Task 9: Make the separate Products page consume the live backend catalog

**Repository:** `/Users/lucasfeng/Documents/ChatGPT/restar app/camaroom-web-proof-led-redesign`

**Files:**
- Modify: `products.html`
- Modify: `assets/js/content-pages.js`
- Modify: `assets/css/content-pages.css`
- Modify: `test/content-pages.test.js`

**Step 1: Add failing integration assertions**

Update `test/content-pages.test.js` to assert that `products.html` loads scripts in this order:

```text
assets/js/countries.js
assets/data/products.js
assets/js/catalog.js
assets/js/content-pages.js
```

Assert `content-pages.js` constructs `RSCatalog.createLoader`, passes the current `?country=` value, renders `price` with `currency`, renders stock availability, and does not replace a successful empty result with static products.

**Step 2: Run and confirm RED**

Run: `node --test test/content-pages.test.js test/catalog.test.js`

Expected: Products page does not load or call the catalog loader.

**Step 3: Connect the page to the shared loader**

Add `assets/js/catalog.js` before `content-pages.js` in `products.html`. In `content-pages.js`, keep bundled `PRODUCTS` only as the loader fallback. Use the same origin as the homepage:

```javascript
const PRODUCT_API_ORIGIN = "https://rest-solar-agent-cm.onrender.com";
const loader = window.RSCatalog.createLoader({
  baseUrl: PRODUCT_API_ORIGIN,
  fetch: window.fetch.bind(window),
  fallbackProducts: PRODUCTS,
});
```

Make product rendering async. Render a loading state, then render `result.products` and `result.inventory`. If `result.source === "fallback"`, show the existing non-blocking catalog-unavailable notice. A zero-length API result renders the translated no-products state.

Price display rules:

- numeric price plus currency: formatted local price;
- no price: existing “Contact us”/“Request a quote” copy;
- stock `> 0`: available;
- stock `=== 0`: out of stock;
- absent stock in legacy fallback: omit stock label.

**Step 4: Run website tests**

Run: `node --test test/*.test.js`

Expected: all pass.

**Step 5: Commit in the website repository**

```bash
git add products.html assets/js/content-pages.js assets/css/content-pages.css test/content-pages.test.js
git commit -m "feat: sync products page with managed catalog"
```

---

### Task 10: End-to-end verification, live smoke test, and release

**Files:**
- Modify only if a verification failure identifies a real defect.

**Step 1: Run the complete backend suite**

From `/Users/lucasfeng/Documents/ChatGPT/restar app/rest-solar-agent-product-admin`:

```bash
pytest -q
```

Expected: zero failures.

**Step 2: Run the complete website suite**

From `/Users/lucasfeng/Documents/ChatGPT/restar app/camaroom-web-proof-led-redesign`:

```bash
node --test test/*.test.js
```

Expected: zero failures.

**Step 3: Run local browser acceptance**

Start the backend against a disposable SQLite database and open the admin UI. Verify at desktop and mobile widths:

1. Superadmin sees all countries and the permanent-delete control.
2. A Nigeria country admin sees shared read-only rows plus Nigeria rows.
3. The country admin can add, edit, upload an image, change NGN price, and change stock.
4. Unpublish immediately removes the product from `/api/products?country=NG`.
5. Archive places it under the archived tab; restore returns it to the public API.
6. English, Chinese, and French selectors persist across navigation.
7. Products page and homepage show the same active product set.
8. Customer chat/Gemini does not cite an inactive or archived SKU.

**Step 4: Review the final diff for scope and secrets**

Run in both repositories:

```bash
git status --short
git diff --check
git log --oneline -12
```

Confirm no password, API key, database URL, generated upload, or local database is tracked.

**Step 5: Push the tested backend branch**

From the backend clone:

```bash
git push origin phase-2-build
```

Wait for Render to deploy, then verify `/health`, `/api/products?country=CM`, and admin login. Confirm startup schema upgrade completes without dropping or duplicating product data.

**Step 6: Live disposable-product verification**

Create one clearly named test product in one country, verify public appearance and removal after unpublish, then leave it `archived`. Do not permanently delete real catalog rows during verification.

**Step 7: Push the tested website branch to production**

From the website repository, only after the backend deploy and API verification:

```bash
git push origin HEAD:main
```

Verify `https://restarsolar.net/` and `https://restarsolar.net/products.html` in a clean browser session for CM, NG, SD, and ML.

**Step 8: Record final evidence**

Report exact backend and website commit SHAs, test totals, deployed URLs, and the archived disposable product's SKU. Do not claim completion until both live pages and admin lifecycle have been exercised.
