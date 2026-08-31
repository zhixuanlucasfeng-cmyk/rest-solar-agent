# Multi-Country Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the RestarSolar agent backend a per-country dimension so each of four country admins (CM/NG/SD/ML) sees and manages only its own conversations, orders, and products, with a shared global catalog and reliable Postgres + blob persistence.

**Architecture:** Add a nullable `country` column to `admin_users`, `conversations`, and `products`, and a non-null `country` to an expanded `orders` table. The chat widget passes its country on the WebSocket URL; the backend stamps it onto the conversation. Admin routes filter every query by the logged-in user's country (superadmin = no filter). Uploaded files move from the ephemeral filesystem into a `media_assets` blob table served by a `/media/{id}` route. Accounts are seeded from environment variables on startup.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Jinja2 templates, Tailwind/htmx admin UI, pytest + httpx, Postgres (Neon) in production / in-memory SQLite in tests.

**Spec:** `docs/superpowers/specs/2026-08-30-multi-country-backend-design.md`

## Global Constraints

- Countries are exactly `("CM", "NG", "SD", "ML")`. Default / fallback for any missing or invalid country is `"CM"`.
- `AdminUser.role` values are `"superadmin"` (country `NULL`, sees all) and `"country_admin"` (country set, scoped).
- `Order.status` values: `pending`, `contacted`, `quoted`, `paid`, `shipped`, `closed`. New orders start `pending`.
- `order_number` format: `{COUNTRY}-{YYYYMMDD}-{seq:03d}`, `seq` = that country's order count that day + 1; on unique violation retry with `seq + 1`.
- Country admin email convention (seeding): `{cc}-admin@restsolar.com` (lowercase).
- `SEED_COUNTRY_ADMINS` env format: `cm:password1,ng:password2,sd:password3,ml:password4`.
- Schema is created by `Base.metadata.create_all` against a fresh database. No Alembic. Do not write migration code for existing production rows.
- Existing 169 catalog products keep `country = NULL` (shared) and keep their `image_path` / `datasheet_path` file references. Do not migrate those files into blobs.
- All 64 existing tests must still pass. New columns are nullable or have defaults so `create_all` in the test fixture keeps working.
- TDD: write the failing test first, watch it fail, minimal implementation, watch it pass, commit. Follow existing file/test patterns.

---

### Task 1: Countries module

**Files:**
- Create: `app/countries.py`
- Test: `tests/test_countries.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `COUNTRIES: tuple[str, ...]` — `("CM", "NG", "SD", "ML")`
  - `DEFAULT_COUNTRY: str` — `"CM"`
  - `normalize_country(value: str | None) -> str` — uppercased value if in `COUNTRIES`, else `"CM"`
  - `is_valid_country(value: str | None) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_countries.py
from app.countries import COUNTRIES, DEFAULT_COUNTRY, normalize_country, is_valid_country


def test_country_set():
    assert COUNTRIES == ("CM", "NG", "SD", "ML")
    assert DEFAULT_COUNTRY == "CM"


def test_normalize_valid():
    assert normalize_country("NG") == "NG"
    assert normalize_country("ng") == "NG"
    assert normalize_country(" ml ") == "ML"


def test_normalize_invalid_falls_back():
    assert normalize_country(None) == "CM"
    assert normalize_country("") == "CM"
    assert normalize_country("US") == "CM"
    assert normalize_country("garbage") == "CM"


def test_is_valid_country():
    assert is_valid_country("SD") is True
    assert is_valid_country("sd") is True
    assert is_valid_country("XX") is False
    assert is_valid_country(None) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_countries.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.countries'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/countries.py
COUNTRIES: tuple[str, ...] = ("CM", "NG", "SD", "ML")
DEFAULT_COUNTRY: str = "CM"


def is_valid_country(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().upper() in COUNTRIES


def normalize_country(value: str | None) -> str:
    if isinstance(value, str) and value.strip().upper() in COUNTRIES:
        return value.strip().upper()
    return DEFAULT_COUNTRY
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_countries.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/countries.py tests/test_countries.py
git commit -m "feat: add countries module (CM/NG/SD/ML, normalize helper)"
```

---

### Task 2: Schema changes — country columns, MediaAsset, expanded Order

**Files:**
- Modify: `app/db/models.py`
- Test: `tests/test_models.py` (append)

**Interfaces:**
- Consumes: nothing (pure schema).
- Produces:
  - `AdminUser.country: str | None`
  - `Conversation.country: str | None` (indexed)
  - `Product.country: str | None` (indexed), `Product.image_asset_id: int | None`, `Product.datasheet_asset_id: int | None`
  - `ProductImage.asset_id: int | None`
  - `Order.country: str` (non-null), `Order.conversation_id: int | None`, `Order.contact: str | None`, `Order.items: str`, `Order.notes: str | None`, `Order.total_xaf: float | None`
  - `MediaAsset` model: `id`, `kind`, `content_type`, `data` (bytes), `filename`, `created_at`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py  (append)
import pytest
from sqlalchemy import select
from app.db.models import (
    Base, AdminUser, Conversation, Product, ProductImage, Order, MediaAsset,
)


@pytest.mark.asyncio
async def test_country_columns_default_null(db):
    u = AdminUser(email="a@b.c", password_hash="x", role="superadmin")
    c = Conversation(session_id="s1", language="en")
    p = Product(name="Panel", sku="ZZ-1")
    db.add_all([u, c, p])
    await db.commit()
    assert u.country is None
    assert c.country is None
    assert p.country is None
    assert p.image_asset_id is None


@pytest.mark.asyncio
async def test_media_asset_roundtrips_bytes(db):
    m = MediaAsset(kind="image", content_type="image/jpeg", data=b"\xff\xd8\xff", filename="x.jpg")
    db.add(m)
    await db.commit()
    got = (await db.execute(select(MediaAsset).where(MediaAsset.id == m.id))).scalar_one()
    assert got.data == b"\xff\xd8\xff"
    assert got.content_type == "image/jpeg"


@pytest.mark.asyncio
async def test_order_has_country_and_new_fields(db):
    o = Order(
        order_number="NG-20260830-001", country="NG", customer_name="Ada",
        contact="+234...", items="2x ZZ-1", notes="urgent", total_xaf=None,
    )
    db.add(o)
    await db.commit()
    got = (await db.execute(select(Order).where(Order.order_number == "NG-20260830-001"))).scalar_one()
    assert got.country == "NG"
    assert got.status == "pending"
    assert got.items == "2x ZZ-1"
    assert got.conversation_id is None


@pytest.mark.asyncio
async def test_product_image_asset_id_nullable(db):
    p = Product(name="P", sku="ZZ-2")
    db.add(p)
    await db.flush()
    img = ProductImage(product_id=p.id, path="static/x.jpg", sort_order=0)
    db.add(img)
    await db.commit()
    assert img.asset_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v -k "country_columns or media_asset or order_has_country or image_asset_id"`
Expected: FAIL — `ImportError: cannot import name 'MediaAsset'` / `AttributeError` on `.country`.

- [ ] **Step 3: Write minimal implementation**

In `app/db/models.py`:

Add `LargeBinary` to the imports from `sqlalchemy`:
```python
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, Float, LargeBinary
```

Add to `Conversation`:
```python
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True, default=None)
```

Add to `Product` (after `use_cases`):
```python
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, index=True, default=None)
    image_asset_id: Mapped[int | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    datasheet_asset_id: Mapped[int | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
```

Add to `ProductImage`:
```python
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
```

Replace the body of `Order` with:
```python
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, index=True, default="CM")
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(200), nullable=True)
    items: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_xaf: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

Add to `AdminUser`:
```python
    country: Mapped[str | None] = mapped_column(String(2), nullable=True, default=None)
```

Add a new model (place after `ProductImage`):
```python
class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20))          # "image" | "datasheet"
    content_type: Mapped[str] = mapped_column(String(100))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_models.py -v`
Expected: PASS (new + existing model tests)

Run: `pytest -q`
Expected: full suite still green (schema change is additive).

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py tests/test_models.py
git commit -m "feat: add country columns, MediaAsset table, expanded Order fields"
```

---

### Task 3: Media blob storage — `media_url` helper, `/media/{id}` route, upload rewrite

**Files:**
- Create: `app/media.py`
- Create: `app/api/media.py`
- Modify: `app/main.py` (register the media router + Jinja global)
- Modify: `app/admin/routes.py` (rewrite `_save_upload`, use asset ids in create/edit)
- Modify: `app/api/products.py` (use `media_url`)
- Modify: `templates/admin/products.html`, `templates/admin/product_edit.html` (use `media_url`)
- Test: `tests/test_media.py`

**Interfaces:**
- Consumes: `MediaAsset` (Task 2).
- Produces:
  - `app.media.media_url(asset_id: int | None, legacy_path: str | None) -> str | None`
  - `app.media.save_upload(db, file: UploadFile, kind: str) -> int` — writes a `MediaAsset`, returns its id
  - `GET /media/{asset_id}` route

- [ ] **Step 1: Write the failing test**

```python
# tests/test_media.py
import io
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from starlette.datastructures import UploadFile, Headers

from app.main import app
from app.db.models import Base, MediaAsset
from app.media import media_url, save_upload


def test_media_url_prefers_asset_over_path():
    assert media_url(7, "static/x.jpg") == "/media/7"
    assert media_url(None, "static/x.jpg") == "/static/x.jpg".lstrip("/") and media_url(None, "static/x.jpg") == "/static/x.jpg"
    assert media_url(None, None) is None


@pytest.mark.asyncio
async def test_save_upload_and_serve():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    upload = UploadFile(
        filename="p.jpg",
        file=io.BytesIO(b"\xff\xd8\xffDATA"),
        headers=Headers({"content-type": "image/jpeg"}),
    )
    async with Session() as s:
        asset_id = await save_upload(s, upload, "image")
        await s.commit()

    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/media/{asset_id}")
    app.dependency_overrides.clear()
    await engine.dispose()

    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xffDATA"
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.asyncio
async def test_media_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/media/999999")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_media.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.media'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/media.py
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import MediaAsset


def media_url(asset_id: int | None, legacy_path: str | None) -> str | None:
    if asset_id is not None:
        return f"/media/{asset_id}"
    if legacy_path:
        return "/" + legacy_path.lstrip("/")
    return None


async def save_upload(db: AsyncSession, file: UploadFile, kind: str) -> int:
    data = await file.read()
    asset = MediaAsset(
        kind=kind,
        content_type=file.content_type or "application/octet-stream",
        data=data,
        filename=file.filename,
    )
    db.add(asset)
    await db.flush()
    return asset.id
```

```python
# app/api/media.py
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.db.models import MediaAsset

router = APIRouter()


@router.get("/media/{asset_id}")
async def get_media(asset_id: int, db: AsyncSession = Depends(get_db)):
    asset = (await db.execute(select(MediaAsset).where(MediaAsset.id == asset_id))).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=asset.data,
        media_type=asset.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

In `app/main.py`:
- import and include the router: `from app.api.media import router as media_router` then `app.include_router(media_router)` (next to the other `include_router` calls).
- register the Jinja global after `templates = Jinja2Templates(directory="templates")`:
  ```python
  from app.media import media_url
  templates.env.globals["media_url"] = media_url
  ```
- Do the same in `app/admin/routes.py` where its own `templates = Jinja2Templates(...)` is defined:
  ```python
  from app.media import media_url
  templates.env.globals["media_url"] = media_url
  ```

In `app/admin/routes.py`:
- Delete the `_save_upload` function.
- Add `from app.media import save_upload`.
- In `create_product`, replace the datasheet/primary-image/gallery blocks:
  ```python
      if datasheet and datasheet.filename:
          product.datasheet_asset_id = await save_upload(db, datasheet, "datasheet")
      if primary_image and primary_image.filename:
          product.image_asset_id = await save_upload(db, primary_image, "image")

      db.add(product)
      await db.flush()

      for i, img in enumerate([g for g in (gallery_images or []) if g and g.filename]):
          asset_id = await save_upload(db, img, "image")
          db.add(ProductImage(product_id=product.id, asset_id=asset_id, sort_order=i))
  ```
- In `update_product`, mirror the same change (set `*_asset_id`, gallery `ProductImage(product_id=..., asset_id=asset_id, sort_order=...)`).

In `app/api/products.py`, replace the image/images/datasheet fields:
```python
            "image": media_url(p.image_asset_id, p.image_path),
            "images": [media_url(img.asset_id, img.path) for img in p.images],
            "datasheet": media_url(p.datasheet_asset_id, p.datasheet_path),
```
Add `from app.media import media_url`.

In `templates/admin/products.html`:
- line ~81-82: `{% set img = media_url(p.image_asset_id, p.image_path) %}{% if img %}<img src="{{ img }}" ...>`
- line ~111-112: `{% set ds = media_url(p.datasheet_asset_id, p.datasheet_path) %}{% if ds %}<a href="{{ ds }}" ...>PDF ↓</a>{% endif %}`

In `templates/admin/product_edit.html`:
- primary image / datasheet / gallery `<img src>` / links: replace `/{{ p.image_path }}` → `{{ media_url(p.image_asset_id, p.image_path) }}`, `/{{ p.datasheet_path }}` → `{{ media_url(p.datasheet_asset_id, p.datasheet_path) }}`, and in the gallery loop `/{{ img.path }}` → `{{ media_url(img.asset_id, img.path) }}`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_media.py tests/test_admin_routes.py tests/test_products_api.py -v`
Expected: PASS

Run: `pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add app/media.py app/api/media.py app/main.py app/admin/routes.py app/api/products.py templates/admin/products.html templates/admin/product_edit.html tests/test_media.py
git commit -m "feat: store product uploads as DB blobs served via /media/{id}"
```

---

### Task 4: Widget + WebSocket country tagging

**Files:**
- Modify: `static/widget.js`
- Modify: `app/api/ws.py`
- Modify: `app/api/chat.py` (`ChatRequest.country`)
- Test: `tests/test_websocket.py` (append), `tests/test_chat_api.py` (append)

**Interfaces:**
- Consumes: `normalize_country` (Task 1), `Conversation.country` (Task 2).
- Produces: `customer_ws` accepts `?country=`; `Conversation` rows created there carry the normalized country. `ChatRequest` has optional `country`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_websocket.py  (append — match the file's existing client/fixture style)
import pytest
from sqlalchemy import select
from app.db.models import Conversation


@pytest.mark.asyncio
async def test_ws_stores_country(ws_client_factory):
    # ws_client_factory is the existing helper in this file that opens a
    # customer websocket for a given path and yields (client, db_session).
    async with ws_client_factory("/ws/424242?country=NG") as (ws, db):
        ws.send_json({"message": "hi"})
        _ = ws.receive_json()
    conv = (await db.execute(
        select(Conversation).where(Conversation.session_id == "conv-424242")
    )).scalar_one()
    assert conv.country == "NG"


@pytest.mark.asyncio
async def test_ws_missing_country_defaults_cm(ws_client_factory):
    async with ws_client_factory("/ws/424243") as (ws, db):
        ws.send_json({"message": "hi"})
        _ = ws.receive_json()
    conv = (await db.execute(
        select(Conversation).where(Conversation.session_id == "conv-424243")
    )).scalar_one()
    assert conv.country == "CM"


@pytest.mark.asyncio
async def test_ws_invalid_country_defaults_cm(ws_client_factory):
    async with ws_client_factory("/ws/424244?country=US") as (ws, db):
        ws.send_json({"message": "hi"})
        _ = ws.receive_json()
    conv = (await db.execute(
        select(Conversation).where(Conversation.session_id == "conv-424244")
    )).scalar_one()
    assert conv.country == "CM"
```

> If `tests/test_websocket.py` does not already expose a reusable
> `ws_client_factory`, adapt these to the pattern the file *does* use
> (e.g. `TestClient(app).websocket_connect(...)` with a dependency
> override for `get_db`). Keep the three assertions: `?country=NG` → `"NG"`,
> missing → `"CM"`, invalid → `"CM"`.

```python
# tests/test_chat_api.py  (append)
def test_chat_request_accepts_country():
    from app.api.chat import ChatRequest
    req = ChatRequest(message="hi", session_id="s", country="NG")
    assert req.country == "NG"
    req2 = ChatRequest(message="hi", session_id="s")
    assert req2.country is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_websocket.py -v -k country` and `pytest tests/test_chat_api.py -v -k country`
Expected: FAIL — country not stored / `ChatRequest` has no `country`.

- [ ] **Step 3: Write minimal implementation**

`app/api/chat.py` — add to `ChatRequest`:
```python
    country: str | None = None
```

`app/api/ws.py`:
- imports: `from fastapi import ... , Query` and `from app.countries import normalize_country`.
- change the customer endpoint signature:
  ```python
  @router.websocket("/ws/{conversation_id}")
  async def customer_ws(
      conversation_id: int,
      ws: WebSocket,
      country: str = Query("CM"),
      db: AsyncSession = Depends(get_db),
  ):
  ```
- where the `Conversation` is created (currently `conv = Conversation(session_id=session_id, language="en")`):
  ```python
      conv = Conversation(session_id=session_id, language="en", country=normalize_country(country))
  ```

`static/widget.js`:
- near the top, capture the country from the embedding script tag:
  ```javascript
  const COUNTRY = (document.currentScript && document.currentScript.dataset.country
                   ? document.currentScript.dataset.country
                   : 'CM').toUpperCase();
  ```
  (`document.currentScript` is valid during the initial synchronous IIFE run.)
- in `connectWS`, append the query param:
  ```javascript
  ws = new WebSocket(protocol + '://' + location.host + '/ws/' + CONV_ID + '?country=' + encodeURIComponent(COUNTRY));
  ```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_websocket.py tests/test_chat_api.py -v`
Expected: PASS

Run: `pytest -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add static/widget.js app/api/ws.py app/api/chat.py tests/test_websocket.py tests/test_chat_api.py
git commit -m "feat: widget passes country on the chat websocket; stamp it on the conversation"
```

---

### Task 5: Public product feed — country filter

**Files:**
- Modify: `app/api/products.py`
- Test: `tests/test_products_api.py` (append)

**Interfaces:**
- Consumes: `is_valid_country` (Task 1), `Product.country` (Task 2).
- Produces: `GET /api/products?country=` filters `country IS NULL OR country = :cc`; no/invalid param → `country IS NULL` only.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_products_api.py  (append — reuse this file's existing client + db override fixture)
import pytest
from app.db.models import Product


@pytest.mark.asyncio
async def test_products_feed_country_filter(products_client, seed_db):
    # seed_db: fixture in this file that yields a Session; add rows then commit.
    async with seed_db() as s:
        s.add_all([
            Product(name="Shared", sku="SH-1", country=None),
            Product(name="NG only", sku="NG-1", country="NG"),
            Product(name="ML only", sku="ML-1", country="ML"),
        ])
        await s.commit()

    r_all = await products_client.get("/api/products")
    skus_default = {p["sku"] for p in r_all.json()}
    assert skus_default == {"SH-1"}

    r_ng = await products_client.get("/api/products?country=NG")
    skus_ng = {p["sku"] for p in r_ng.json()}
    assert skus_ng == {"SH-1", "NG-1"}

    r_bad = await products_client.get("/api/products?country=US")
    assert {p["sku"] for p in r_bad.json()} == {"SH-1"}
```

> Adapt `products_client` / `seed_db` names to whatever `tests/test_products_api.py` already defines.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_products_api.py -v -k country_filter`
Expected: FAIL — feed ignores `country`, returns all rows.

- [ ] **Step 3: Write minimal implementation**

`app/api/products.py`:
```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, or_
from app.countries import is_valid_country
...

@router.get("/api/products")
async def list_products(country: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    stmt = select(Product).options(selectinload(Product.images)).order_by(Product.category, Product.sku)
    if country and is_valid_country(country):
        stmt = stmt.where(or_(Product.country.is_(None), Product.country == country.upper()))
    else:
        stmt = stmt.where(Product.country.is_(None))
    result = await db.execute(stmt)
    products = result.scalars().all()
    return [ ... ]  # unchanged body
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_products_api.py -v`
Expected: PASS

Run: `pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add app/api/products.py tests/test_products_api.py
git commit -m "feat: /api/products country filter (shared catalog + one country)"
```

---

### Task 6: Admin scoping helpers

**Files:**
- Modify: `app/admin/deps.py`
- Test: `tests/test_admin_scope.py` (create)

**Interfaces:**
- Consumes: `AdminUser` (Task 2).
- Produces:
  - `scope_clause(user: AdminUser, model) -> ColumnElement` — `sqlalchemy.true()` for superadmin, else `model.country == user.country`
  - `assert_visible(user: AdminUser, obj) -> None` — raises `HTTPException(404)` unless superadmin or `obj.country == user.country`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_scope.py
import pytest
from fastapi import HTTPException
from app.admin.deps import scope_clause, assert_visible
from app.db.models import AdminUser, Conversation


class _Obj:
    def __init__(self, country):
        self.country = country


def test_scope_clause_superadmin_is_true():
    su = AdminUser(email="s", password_hash="x", role="superadmin", country=None)
    clause = scope_clause(su, Conversation)
    assert clause.compare(__import__("sqlalchemy").true())


def test_scope_clause_country_admin():
    ca = AdminUser(email="c", password_hash="x", role="country_admin", country="NG")
    clause = scope_clause(ca, Conversation)
    # renders to "conversations.country = :country_1"
    assert "country" in str(clause)


def test_assert_visible():
    su = AdminUser(email="s", password_hash="x", role="superadmin", country=None)
    ca = AdminUser(email="c", password_hash="x", role="country_admin", country="NG")
    assert_visible(su, _Obj("ML"))          # superadmin: no raise
    assert_visible(ca, _Obj("NG"))          # same country: no raise
    with pytest.raises(HTTPException) as e:
        assert_visible(ca, _Obj("ML"))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        assert_visible(ca, _Obj(None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_admin_scope.py -v`
Expected: FAIL — `ImportError: cannot import name 'scope_clause'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/admin/deps.py`:
```python
from sqlalchemy import true

def scope_clause(user: AdminUser, model):
    """WHERE clause restricting `model` rows to the user's country.
    Superadmin (country is None) sees everything."""
    if user.country is None:
        return true()
    return model.country == user.country


def assert_visible(user: AdminUser, obj) -> None:
    """404 if `obj` is outside the user's country scope."""
    if user.country is None:
        return
    if getattr(obj, "country", None) != user.country:
        raise HTTPException(status_code=404, detail="Not found")
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_admin_scope.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/admin/deps.py tests/test_admin_scope.py
git commit -m "feat: admin country-scoping helpers (scope_clause, assert_visible)"
```

---

### Task 7: Scope conversations, orders, tickets, dashboard

**Files:**
- Modify: `app/admin/routes.py`
- Test: `tests/test_admin_routes.py` (append; add a `country_client` fixture)

**Interfaces:**
- Consumes: `scope_clause`, `assert_visible` (Task 6); `Order.country`, `Conversation.country` (Task 2).
- Produces: `/admin/conversations`, `/admin/conversations/{id}`, `/admin/orders`, `/admin/orders/{id}/status`, `/admin/tickets`, `/admin/tickets/{id}/close`, `/admin/dashboard` all country-scoped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_routes.py  (append)
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, AdminUser, Conversation, Order, Ticket
from app.admin.auth import hash_password, create_access_token


@pytest.fixture
async def scoped_env():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        su = AdminUser(email="su@x.c", password_hash=hash_password("p"), role="superadmin", country=None)
        ng = AdminUser(email="ng@x.c", password_hash=hash_password("p"), role="country_admin", country="NG")
        s.add_all([su, ng])
        await s.flush()
        c_ng = Conversation(session_id="c-ng", language="en", country="NG")
        c_ml = Conversation(session_id="c-ml", language="en", country="ML")
        s.add_all([c_ng, c_ml])
        await s.flush()
        s.add_all([
            Order(order_number="NG-1", country="NG", customer_name="A", items=""),
            Order(order_number="ML-1", country="ML", customer_name="B", items=""),
            Ticket(conversation_id=c_ng.id, subject="ng t", body="x", status="open"),
            Ticket(conversation_id=c_ml.id, subject="ml t", body="x", status="open"),
        ])
        await s.commit()
        su_tok = create_access_token({"sub": str(su.id), "role": "superadmin"})
        ng_tok = create_access_token({"sub": str(ng.id), "role": "country_admin"})
        ng_conv_id = c_ml.id  # a conversation NOT visible to NG

    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    def client(tok):
        return AsyncClient(transport=transport, base_url="http://test", cookies={"admin_token": tok})

    yield client, su_tok, ng_tok, ng_conv_id
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_country_admin_sees_only_own_orders(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/orders")
    assert b"NG-1" in r.content and b"ML-1" not in r.content


@pytest.mark.asyncio
async def test_superadmin_sees_all_orders(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(su_tok) as c:
        r = await c.get("/admin/orders")
    assert b"NG-1" in r.content and b"ML-1" in r.content


@pytest.mark.asyncio
async def test_country_admin_conversation_detail_cross_country_404(scoped_env):
    client, su_tok, ng_tok, ml_conv_id = scoped_env
    async with client(ng_tok) as c:
        r = await c.get(f"/admin/conversations/{ml_conv_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_country_admin_tickets_scoped(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/tickets")
    assert b"ng t" in r.content and b"ml t" not in r.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_routes.py -v -k "scoped or country_admin or superadmin_sees"`
Expected: FAIL — routes return all rows / detail returns 200.

- [ ] **Step 3: Write minimal implementation**

In `app/admin/routes.py` add imports:
```python
from app.admin.deps import get_current_admin, require_superadmin, scope_clause, assert_visible
```

`conversations` list — add `.where(scope_clause(current_user, Conversation))`:
```python
    result = await db.execute(
        select(Conversation)
        .where(scope_clause(current_user, Conversation))
        .order_by(desc(Conversation.created_at)).limit(50)
    )
```

`conversation_detail` — after fetching `conv`:
```python
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    assert_visible(current_user, conv)
```

`orders_page`:
```python
    result = await db.execute(
        select(Order).where(scope_clause(current_user, Order)).order_by(desc(Order.created_at))
    )
```

`update_order_status` — after fetching `order`:
```python
    if order:
        assert_visible(current_user, order)
        order.status = status
        await db.commit()
```

`tickets_page` — tickets have no `country`; scope via the linked conversation:
```python
    stmt = select(Ticket).order_by(desc(Ticket.created_at))
    if current_user.country is not None:
        stmt = (
            select(Ticket)
            .join(Conversation, Ticket.conversation_id == Conversation.id)
            .where(Conversation.country == current_user.country)
            .order_by(desc(Ticket.created_at))
        )
    result = await db.execute(stmt)
```

`close_ticket` — after fetching `ticket`:
```python
    if ticket:
        if current_user.country is not None:
            conv = (await db.execute(
                select(Conversation).where(Conversation.id == ticket.conversation_id)
            )).scalar_one_or_none()
            if conv is None or conv.country != current_user.country:
                raise HTTPException(status_code=404, detail="Not found")
        ticket.status = "closed"
        await db.commit()
```

`dashboard`:
```python
    conv_count = (await db.execute(
        select(Conversation).where(scope_clause(current_user, Conversation))
    )).scalars().all()
    open_tickets_stmt = select(Ticket).where(Ticket.status == "open")
    if current_user.country is not None:
        open_tickets_stmt = (
            select(Ticket).join(Conversation, Ticket.conversation_id == Conversation.id)
            .where(Ticket.status == "open", Conversation.country == current_user.country)
        )
    ticket_count = (await db.execute(open_tickets_stmt)).scalars().all()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_admin_routes.py -v`
Expected: PASS

Run: `pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add app/admin/routes.py tests/test_admin_routes.py
git commit -m "feat: country-scope admin conversations, orders, tickets, dashboard"
```

---

### Task 8: Scope products; lock Rules to superadmin; sidebar

**Files:**
- Modify: `app/admin/routes.py`
- Modify: `templates/admin/base.html`, `templates/admin/products.html`
- Test: `tests/test_admin_routes.py` (append)

**Interfaces:**
- Consumes: Task 6 helpers; `Product.country` (Task 2).
- Produces: product list shows shared (read-only) + own; create forces `user.country`; edit/delete/image ops 403 on shared products for country admins; `/admin/rules*` requires superadmin; sidebar hides Rules/Users/Reports for country admins.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_admin_routes.py  (append; reuse scoped_env from Task 7)
import pytest
from app.db.models import Product


@pytest.fixture
async def product_env(scoped_env):
    # add products to the same in-memory DB via a fresh session
    client, su_tok, ng_tok, _ = scoped_env
    from app.db.session import get_db
    override = app.dependency_overrides[get_db]
    agen = override()
    s = await agen.__anext__()
    s.add_all([
        Product(name="Shared panel", sku="SHARE-1", country=None),
        Product(name="NG panel", sku="NGP-1", country="NG"),
    ])
    await s.commit()
    prods = {p.sku: p.id for p in (await s.execute(__import__("sqlalchemy").select(Product))).scalars()}
    try:
        await agen.__anext__()
    except StopAsyncIteration:
        pass
    return client, su_tok, ng_tok, prods


@pytest.mark.asyncio
async def test_country_admin_product_list_shows_shared_and_own(product_env):
    client, su_tok, ng_tok, prods = product_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/products")
    assert b"SHARE-1" in r.content and b"NGP-1" in r.content


@pytest.mark.asyncio
async def test_country_admin_cannot_edit_shared_product(product_env):
    client, su_tok, ng_tok, prods = product_env
    async with client(ng_tok) as c:
        r = await c.post(f"/admin/products/{prods['SHARE-1']}/edit",
                         data={"name": "hacked", "sku": "SHARE-1"}, follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_country_admin_create_forces_own_country(product_env):
    client, su_tok, ng_tok, prods = product_env
    async with client(ng_tok) as c:
        await c.post("/admin/products",
                     data={"name": "New NG", "sku": "NEWNG-1", "country": "ML"},
                     follow_redirects=False)
        r = await c.get("/admin/products")
    assert b"NEWNG-1" in r.content  # visible to NG => it was tagged NG, not ML


@pytest.mark.asyncio
async def test_country_admin_rules_forbidden(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/rules", follow_redirects=False)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_country_admin_sidebar_hides_rules(scoped_env):
    client, su_tok, ng_tok, _ = scoped_env
    async with client(ng_tok) as c:
        r = await c.get("/admin/dashboard")
    assert b'href="/admin/rules"' not in r.content
    assert b'href="/admin/users"' not in r.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_routes.py -v -k "product_env or shared_product or forces_own or rules_forbidden or sidebar_hides"`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`app/admin/routes.py`:

`products_page` — visibility filter for country admins:
```python
    stmt = select(Product).options(selectinload(Product.images)).order_by(Product.category, Product.sku)
    if current_user.country is not None:
        stmt = stmt.where(or_(Product.country.is_(None), Product.country == current_user.country))
    if category:
        stmt = stmt.where(Product.category == category)
```
Add `from sqlalchemy import select, desc, func, or_` (add `or_`). Pass `current_user` into the template context (already passed as `current_user`).

`create_product` — accept an optional `country` form field and force scope:
```python
    country: str = Form(None),
    ...
    fields = _product_fields_from_form(...)
    if current_user.country is not None:
        fields["country"] = current_user.country
    elif country:
        from app.countries import normalize_country
        fields["country"] = normalize_country(country)
    product = Product(**fields)
```
Add `country=fields.get("country")` handling: update `_product_fields_from_form` to accept and pass `country` (add param with default `None`, include `country=country or None` in the returned dict), OR simply set `product.country` after construction. Simplest: after `product = Product(**fields)` do:
```python
    if current_user.country is not None:
        product.country = current_user.country
    elif country:
        from app.countries import normalize_country
        product.country = normalize_country(country)
```
(and do NOT add `country` to `_product_fields_from_form`).

`edit_product_page`, `update_product`, `delete_product`, `delete_product_image` — after fetching `product` (or the image's product), add:
```python
    assert_visible(current_user, product)
    if current_user.country is not None and product.country is None:
        raise HTTPException(status_code=403, detail="Shared catalog is superadmin-only")
```
For `update_product` also re-assert after applying fields that `product.country` is not changed by a country admin: since a country admin's product always has `country == current_user.country` and we 403 on shared, no extra guard needed; just don't let `_product_fields_from_form` touch `country` (it doesn't).

`rules_page`, `create_rule`, `delete_rule` — change the dependency from `get_current_admin` to `require_superadmin`:
```python
    current_user: AdminUser = Depends(require_superadmin),
```

`templates/admin/base.html` — move the Rules link inside the existing superadmin block:
```html
      {% if current_user.role == "superadmin" %}
      <a href="/admin/rules" class="hover:underline">Rules</a>
      <a href="/admin/users" class="hover:underline">Users</a>
      <a href="/admin/reports" class="hover:underline">Reports</a>
      {% endif %}
```

`templates/admin/products.html`:
- add a "Country" column header and cell:
  ```html
  <td class="p-3 text-xs">{{ p.country or 'Shared' }}</td>
  ```
- in the actions cell, gate Edit/Delete for shared products when the viewer is a country admin:
  ```html
  {% if current_user.role == "superadmin" or p.country == current_user.country %}
    <a href="/admin/products/{{ p.id }}/edit" ...>Edit</a>
    <form action="/admin/products/{{ p.id }}/delete" ...>...</form>
  {% else %}
    <span class="text-gray-400 text-xs">read-only</span>
  {% endif %}
  ```
- in the create form, show a country `<select>` only for superadmin:
  ```html
  {% if current_user.role == "superadmin" %}
  <select name="country" class="border rounded px-3 py-2 text-sm">
    <option value="">Shared (all countries)</option>
    <option value="CM">CM</option><option value="NG">NG</option>
    <option value="SD">SD</option><option value="ML">ML</option>
  </select>
  {% endif %}
  ```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_admin_routes.py -v`
Expected: PASS

Run: `pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add app/admin/routes.py templates/admin/base.html templates/admin/products.html tests/test_admin_routes.py
git commit -m "feat: country-scope products; shared catalog superadmin-only; lock Rules"
```

---

### Task 9: `create_order` agent tool

**Files:**
- Modify: `app/tools/order.py` (add `CreateOrderTool`)
- Modify: `app/tools/__init__.py` (register it, thread `conversation` through `get_tools`)
- Modify: `app/agent/orchestrator.py` (pass `conv` into `get_tools` / `get_tool_map` at both call sites)
- Test: `tests/test_order_tool.py` (append)

**Interfaces:**
- Consumes: `Order` (Task 2), `Conversation` (has `.country`, `.id`).
- Produces:
  - `get_tools(db, conversation=None)` / `get_tool_map(db, conversation=None)` — optional 2nd arg
  - `CreateOrderTool(db, conversation)` with `name = "create_order"`, LLM params `customer_name`, `contact`, `items`, `notes`
  - `app.tools.order.next_order_number(db, country) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_order_tool.py  (append)
import pytest
from sqlalchemy import select
from app.db.models import Conversation, Order
from app.tools.order import CreateOrderTool, next_order_number


@pytest.mark.asyncio
async def test_create_order_inherits_conversation_country(db):
    conv = Conversation(session_id="s-sd", language="en", country="SD")
    db.add(conv)
    await db.flush()

    tool = CreateOrderTool(db, conv)
    result = await tool.call({
        "customer_name": "Omar", "contact": "+249...", "items": "2x INV-1", "notes": "roof job",
    })
    await db.commit()

    order = (await db.execute(select(Order))).scalars().one()
    assert order.country == "SD"
    assert order.conversation_id == conv.id
    assert order.status == "pending"
    assert order.order_number.startswith("SD-")
    assert result["order_number"] == order.order_number


@pytest.mark.asyncio
async def test_next_order_number_increments_per_country_per_day(db):
    conv = Conversation(session_id="s", language="en", country="NG")
    db.add(conv)
    await db.flush()
    n1 = await next_order_number(db, "NG")
    db.add(Order(order_number=n1, country="NG", items=""))
    await db.flush()
    n2 = await next_order_number(db, "NG")
    assert n1.endswith("-001")
    assert n2.endswith("-002")


@pytest.mark.asyncio
async def test_create_order_tool_in_definition():
    from app.tools import get_tools
    names = {t.name for t in get_tools(db=None, conversation=None)}
    assert "create_order" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_tool.py -v -k "create_order or next_order_number"`
Expected: FAIL — `ImportError: cannot import name 'CreateOrderTool'`

- [ ] **Step 3: Write minimal implementation**

Append to `app/tools/order.py`:
```python
from datetime import datetime
from sqlalchemy import func
from app.countries import normalize_country


async def next_order_number(db: AsyncSession, country: str) -> str:
    cc = normalize_country(country)
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"{cc}-{today}-"
    count = await db.scalar(
        select(func.count()).select_from(Order).where(Order.order_number.like(prefix + "%"))
    )
    return f"{prefix}{count + 1:03d}"


class CreateOrderTool(BaseTool):
    name = "create_order"
    description = (
        "Record a purchase order after the customer has explicitly confirmed they "
        "want to buy or be contacted to complete a purchase. Captures name, contact, "
        "and the requested items. Does not take payment."
    )

    def __init__(self, db: AsyncSession, conversation=None):
        self._db = db
        self._conversation = conversation

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_name": {"type": "string", "description": "Customer's name"},
                        "contact": {"type": "string", "description": "Phone / WhatsApp / email"},
                        "items": {"type": "string", "description": "Requested items, e.g. '2x INV-5000, 1x BAT-100'"},
                        "notes": {"type": "string", "description": "Any extra detail (optional)"},
                    },
                    "required": ["customer_name", "contact", "items"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        conv = self._conversation
        country = normalize_country(getattr(conv, "country", None))
        number = await next_order_number(self._db, country)
        order = Order(
            order_number=number,
            country=country,
            conversation_id=getattr(conv, "id", None),
            customer_name=str(params["customer_name"]),
            contact=str(params["contact"]),
            items=str(params["items"]),
            notes=str(params.get("notes") or "") or None,
            status="pending",
        )
        self._db.add(order)
        await self._db.flush()
        return {
            "order_number": order.order_number,
            "status": order.status,
            "confirmation": (
                f"Order {order.order_number} recorded. The {country} team will contact "
                f"{params['contact']} to confirm details and pricing."
            ),
        }
```

`app/tools/__init__.py`:
```python
from app.tools.order import OrderTool, CreateOrderTool


def get_tools(db: AsyncSession, conversation=None) -> list[BaseTool]:
    return [
        CurrencyTool(),
        LogisticsTool(),
        QuoteTool(db),
        OrderTool(db),
        CreateOrderTool(db, conversation),
        TicketTool(db),
    ]


def get_tool_map(db: AsyncSession, conversation=None) -> dict[str, BaseTool]:
    return {t.name: t for t in get_tools(db, conversation)}
```

`app/agent/orchestrator.py` — at both places that call `get_tools(db)` / `get_tool_map(db)` (around lines 253 and 358), pass the conversation object that is already in scope as `conv`:
```python
    tools_list = get_tools(db, conv)
    tool_defs = [t.definition() for t in tools_list]
    tool_map = get_tool_map(db, conv)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_order_tool.py tests/test_orchestrator.py -v`
Expected: PASS

Run: `pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add app/tools/order.py app/tools/__init__.py app/agent/orchestrator.py tests/test_order_tool.py
git commit -m "feat: create_order agent tool, country-tagged from the conversation"
```

---

### Task 10: Seed superadmin + four country admins from env

**Files:**
- Modify: `app/main.py` (`_seed_admin_user` → `_seed_admin_users`)
- Modify: `.env.example`
- Test: `tests/test_seed_admins.py` (create)

**Interfaces:**
- Consumes: `AdminUser` (Task 2), `hash_password`, `is_valid_country`.
- Produces: `app.main._seed_admin_users(session) -> None`; reads `ADMIN_EMAIL` / `ADMIN_PASSWORD` (superadmin) and `SEED_COUNTRY_ADMINS` (`cm:pw,ng:pw,...`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_admins.py
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, AdminUser
from app.main import _seed_admin_users


async def _session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


@pytest.mark.asyncio
async def test_seeds_superadmin_and_country_admins(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", "boss@restsolar.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "bosspw")
    monkeypatch.setenv("SEED_COUNTRY_ADMINS", "cm:p1,ng:p2,sd:p3,ml:p4")
    Session, engine = await _session()
    async with Session() as s:
        await _seed_admin_users(s)
        await _seed_admin_users(s)  # idempotent
    async with Session() as s:
        users = (await s.execute(select(AdminUser))).scalars().all()
    await engine.dispose()

    by_email = {u.email: u for u in users}
    assert by_email["boss@restsolar.com"].role == "superadmin"
    assert by_email["boss@restsolar.com"].country is None
    assert by_email["ng-admin@restsolar.com"].role == "country_admin"
    assert by_email["ng-admin@restsolar.com"].country == "NG"
    assert len(users) == 5


@pytest.mark.asyncio
async def test_malformed_country_admin_entry_is_skipped(monkeypatch):
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("SEED_COUNTRY_ADMINS", "cm:p1,garbage,xx:p9,ng:p2")
    Session, engine = await _session()
    async with Session() as s:
        await _seed_admin_users(s)
    async with Session() as s:
        countries = {u.country for u in (await s.execute(select(AdminUser))).scalars().all()}
    await engine.dispose()
    assert countries == {"CM", "NG"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seed_admins.py -v`
Expected: FAIL — `ImportError: cannot import name '_seed_admin_users'`

- [ ] **Step 3: Write minimal implementation**

In `app/main.py` replace `_seed_admin_user` with:
```python
async def _seed_admin_users(session: AsyncSession) -> None:
    """Seed the superadmin and the per-country admins from env vars.
    Idempotent per email; runs on every startup so accounts survive a DB reset."""
    from app.countries import is_valid_country

    async def _ensure(email: str, password: str, role: str, country: str | None):
        if not email or not password:
            return
        exists = await session.scalar(select(AdminUser).where(AdminUser.email == email))
        if exists:
            return
        session.add(AdminUser(
            email=email, password_hash=hash_password(password), role=role, country=country,
        ))

    await _ensure(os.getenv("ADMIN_EMAIL", ""), os.getenv("ADMIN_PASSWORD", ""), "superadmin", None)

    raw = os.getenv("SEED_COUNTRY_ADMINS", "")
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        if ":" not in entry:
            print(f"[seed] skipping malformed SEED_COUNTRY_ADMINS entry: {entry!r}")
            continue
        cc, _, pw = entry.partition(":")
        cc = cc.strip().upper()
        if not is_valid_country(cc):
            print(f"[seed] skipping unknown country code: {cc!r}")
            continue
        await _ensure(f"{cc.lower()}-admin@restsolar.com", pw.strip(), "country_admin", cc)

    await session.commit()
```

Update the lifespan call site: `await _seed_admin_user(session)` → `await _seed_admin_users(session)`.

`.env.example` — add:
```
# Superadmin (sees all countries)
ADMIN_EMAIL=admin@restsolar.com
ADMIN_PASSWORD=
# Per-country admins, format: cc:password comma-separated. Emails auto: <cc>-admin@restsolar.com
SEED_COUNTRY_ADMINS=cm:changeme1,ng:changeme2,sd:changeme3,ml:changeme4
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_seed_admins.py tests/test_seed.py -v`
Expected: PASS

Run: `pytest -q`
Expected: green (check nothing else imported `_seed_admin_user` by name — grep first: `grep -rn _seed_admin_user app tests`).

- [ ] **Step 5: Commit**

```bash
git add app/main.py .env.example tests/test_seed_admins.py
git commit -m "feat: seed superadmin + 4 country admins from env on startup"
```

---

### Task 11: Infra config + bootstrap runbook

**Files:**
- Modify: `render.yaml`
- Create: `docs/runbooks/2026-08-30-multi-country-cutover.md`
- Modify: `app/db/session.py` (only if the grep in Step 3 shows a hardcoded sqlite fallback worth a comment — otherwise no code change)

**Interfaces:**
- Consumes: everything above.
- Produces: a deploy that points `DATABASE_URL` at Neon and a written cutover procedure.

- [ ] **Step 1: Write the check**

There is no unit test for infra. The verification is: `render.yaml` no longer hardcodes a SQLite `DATABASE_URL`, and the runbook lists every manual step. Add this assertion test so a regression is caught:

```python
# tests/test_render_config.py
import yaml
from pathlib import Path


def test_render_yaml_does_not_pin_sqlite():
    cfg = yaml.safe_load(Path("render.yaml").read_text())
    env = cfg["services"][0]["envVars"]
    db = next((e for e in env if e["key"] == "DATABASE_URL"), None)
    # DATABASE_URL must be set in the dashboard (sync: false), never a literal sqlite value
    assert db is None or "value" not in db or "sqlite" not in str(db.get("value", ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_render_config.py -v`
Expected: FAIL — current `render.yaml` has `DATABASE_URL` with `value: sqlite+aiosqlite:///./data/rest_solar.db`.
(If `pyyaml` is not installed, add `pyyaml` to `requirements.txt` in this task's Step 3 and `pip install -r requirements.txt`.)

- [ ] **Step 3: Apply the config change**

`render.yaml` — change the `DATABASE_URL` entry from a hardcoded value to a dashboard-managed secret:
```yaml
      - key: DATABASE_URL
        sync: false
      - key: SEED_COUNTRY_ADMINS
        sync: false
      - key: ADMIN_EMAIL
        sync: false
      - key: ADMIN_PASSWORD
        sync: false
```

Grep for other hardcoded sqlite references that would override the dashboard value:
```bash
grep -rn "sqlite+aiosqlite:///./data" app/ render.yaml docker-compose*.yml
```
`app/db/session.py` keeps its `os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/rest_solar.db")` default — that is the correct local-dev fallback; leave it, it is only used when the env var is absent.

Create `docs/runbooks/2026-08-30-multi-country-cutover.md`:
```markdown
# Multi-country cutover runbook

## 1. Provision Neon Postgres
- Create a project at neon.tech (free tier).
- Copy the connection string (looks like `postgresql://USER:PASS@HOST/DB?sslmode=require`).

## 2. Render environment
In the rest-solar-agent service → Environment:
- `DATABASE_URL` = the Neon connection string
- `ADMIN_EMAIL` = admin@restsolar.com
- `ADMIN_PASSWORD` = <generate a strong value, store in the team vault>
- `SEED_COUNTRY_ADMINS` = `cm:<pw>,ng:<pw>,sd:<pw>,ml:<pw>` (four distinct strong values)
- Keep `LLM_API_KEY`, `ADMIN_SECRET_KEY`, SMTP vars as they are.

## 3. Deploy
Push `multi-country-backend` → merge to `phase-2-build` → Render auto-deploys.
On boot the app runs `create_all` (builds the full schema on the empty Neon DB)
and `_seed_admin_users` (creates the 5 accounts).

## 4. Load the product catalog (one-time, from a shell with the Neon DATABASE_URL set)
```
export DATABASE_URL='postgresql://...neon...'
python seed.py                          # rules + FAQ RAG
python scripts/ingest_catalog_2026.py   # 169 shared products (country stays NULL)
```

## 5. Verify
- Log in as admin@restsolar.com → see all countries, Rules/Users/Reports visible.
- Log in as ng-admin@restsolar.com → Conversations/Orders/Tickets empty, Products shows
  169 shared (read-only) + none of its own yet, no Rules/Users/Reports in the nav.
- `curl https://rest-solar-agent.onrender.com/api/products` → 169 items.
- `curl 'https://rest-solar-agent.onrender.com/api/products?country=NG'` → 169 items (no NG-specific yet).

## 6. Widget embed snippets (send to the country lead)
Each country site replaces its widget `<script>` with:
```
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="CM"></script>
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="NG"></script>
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="SD"></script>
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="ML"></script>
```

## Known gap
Until the agent-localization spec ships, the agent still answers with Cameroon
shipping / duty / contact figures regardless of `data-country`.
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_render_config.py -v && pytest -q`
Expected: PASS + full suite green.

- [ ] **Step 5: Commit**

```bash
git add render.yaml docs/runbooks/2026-08-30-multi-country-cutover.md tests/test_render_config.py requirements.txt
git commit -m "chore: point DATABASE_URL at Neon via dashboard; add cutover runbook"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| Countries module | 1 |
| `AdminUser.country`, `Conversation.country`, `Product.country`, `Order` expansion, `MediaAsset` | 2 |
| Media storage (`/media`, `media_url`, `_save_upload` rewrite) | 3 |
| Widget `data-country`, WS `?country=`, `ChatRequest.country` | 4 |
| `/api/products?country=` | 5 |
| `scope_clause` / `assert_visible` | 6 |
| Admin scoping: conversations, orders, tickets, dashboard | 7 |
| Admin scoping: products, shared-catalog 403, Rules→superadmin, sidebar | 8 |
| `create_order` tool + orchestrator wiring | 9 |
| `_seed_admin_users` (superadmin + 4 country admins) | 10 |
| Neon `DATABASE_URL`, `render.yaml`, catalog bootstrap, embed snippets | 11 |
| Deferred: agent localization, payments, structured line items | out of scope (noted in runbook "Known gap") |

**2. Placeholder scan** — no "TBD"/"handle edge cases"; each code step has real code. Template edits reference the exact existing lines and the `media_url` / `current_user` names defined in earlier tasks. Test helpers that depend on file-local fixtures (`ws_client_factory`, `products_client`, `seed_db`) carry an explicit "adapt to the pattern this file uses" note because those fixtures already exist in their target files in some form.

**3. Type consistency** — `normalize_country` / `is_valid_country` (Task 1) used consistently in Tasks 4, 5, 8, 9, 10. `media_url(asset_id, legacy_path)` signature identical in Task 3 definition and Tasks 5/8 usage. `scope_clause(user, model)` / `assert_visible(user, obj)` identical in Tasks 6/7/8. `get_tools(db, conversation=None)` — Task 9 updates both the definition and the two orchestrator call sites. `Order` field names (`items`, `contact`, `notes`, `total_xaf`, `country`, `conversation_id`) identical in Tasks 2, 7, 9.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-30-multi-country-backend.md`.
