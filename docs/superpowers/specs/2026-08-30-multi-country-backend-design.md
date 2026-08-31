# Multi-Country Backend — Design Spec

**Date:** 2026-08-30
**Status:** Approved (brainstorming), pending implementation plan
**Branch:** `multi-country-backend` (off `phase-2-build`)

## Problem

The RestarSolar AI agent backend serves one chat widget embedded on four
country marketing sites — Cameroon, Nigeria, Sudan, Mali — but the backend has
no concept of "country":

- `conversations`, `orders`, `products`, `admin_users` have no country column.
- The chat WebSocket does not record which site a conversation came from.
- The agent logic is hardwired to Cameroon (shipping China→Douala, Cameroon
  duty/VAT, Cameroon contacts).
- Production runs on Render's free tier with SQLite on the container's
  ephemeral filesystem and uploads written to the container's `static/`
  directory — **both are wiped on every redeploy and every cold start**, so
  anything created through the live admin panel disappears. Commit `32c7129`
  added Postgres *support* in code but `render.yaml` still points at SQLite,
  so the fix is dormant.

The country team lead asked: give each of the four countries a login that
sees only its own conversations and orders, and lets each country manage its
own products (the catalogs differ between markets).

## Goals

1. Persist data and uploads reliably (Neon Postgres + media blobs in DB).
2. Tag conversations, orders, and products by country.
3. Scope the admin panel so a country admin sees/manages only its own data;
   an internal superadmin sees everything.
4. Shared global product catalog (the existing 169 products) visible to all
   countries, editable only by superadmin; each country adds/manages its own
   extra products.
5. A minimal order record, created by the AI during a conversation, tagged by
   country.
6. Seed one superadmin + four country admins from environment variables.

## Non-Goals (explicitly deferred)

- Localizing the agent's shipping / duty / VAT / contact logic per country
  (separate spec). Until then, NG/SD/ML visitors get Cameroon figures.
- Payments, inventory decrement, structured order line items.
- Migrating the 169 existing product images/datasheets into Postgres (they
  stay as files baked into the Docker image).
- Alembic / migration framework — schema is built by `create_all` against a
  fresh database.

## Countries

Fixed set, ISO-3166 alpha-2: `CM` (Cameroon), `NG` (Nigeria), `SD` (Sudan),
`ML` (Mali). Defined once as `COUNTRIES = ("CM", "NG", "SD", "ML")` in a
shared module (e.g. `app/countries.py`). `CM` is the default / backward-compat
value for any request that does not specify a country.

## Data Model Changes (`app/db/models.py`)

### `AdminUser`
- Add `country: Mapped[str | None]` (nullable, default `None`).
  - `None` → superadmin scope (all countries).
  - set → country admin, scoped to that country.
- `role` stays: values `"superadmin"` and `"country_admin"` (old `"agent"`
  default is replaced; no `agent`-role rows exist in practice).

### `Conversation`
- Add `country: Mapped[str | None]` (nullable, indexed).
  - Written at creation from the WS query param.
  - `None` for legacy rows → visible only to superadmin.

### `Product`
- Add `country: Mapped[str | None]` (nullable, indexed).
  - `None` → shared/global catalog. Existing 169 rows stay `None`.
    Editable only by superadmin.
  - set → that country's own product. Visible to that country + superadmin;
    add/edit/delete allowed for that country's admin.
- `sku` stays globally `unique=True`; new products use new SKUs.
  `ponytail:` comment — if countries later need to reuse SKUs, switch to a
  composite unique `(country, sku)`.
- Add `image_asset_id: Mapped[int | None]` FK → `media_assets.id` (nullable).
- Add `datasheet_asset_id: Mapped[int | None]` FK → `media_assets.id` (nullable).

### `ProductImage`
- Add `asset_id: Mapped[int | None]` FK → `media_assets.id` (nullable).
- `path` column stays (legacy file-based rows).

### `Order` (expand the current stub)
Keep: `id`, `order_number` (unique), `customer_name`, `status`, `created_at`.
Add:
- `country: Mapped[str]` (NOT NULL, indexed).
- `conversation_id: Mapped[int | None]` FK → `conversations.id` (nullable).
- `contact: Mapped[str | None]` (phone / email / WhatsApp, freeform).
- `items: Mapped[str]` (Text) — freeform lines, e.g. `2x SKU-123, 1x SKU-456`.
- `notes: Mapped[str | None]` (Text).
- `total_xaf: Mapped[float | None]`.

`order_number` format: `{COUNTRY}-{YYYYMMDD}-{seq:03d}` where `seq` is the
count of that country's orders that day + 1. Collision-tolerant: on unique
violation, retry with `seq + 1`.

`status` values: `pending`, `contacted`, `quoted`, `paid`, `shipped`, `closed`.

### `MediaAsset` (new table)
- `id: int PK`
- `kind: str` — `"image"` or `"datasheet"`.
- `content_type: str` — e.g. `image/jpeg`, `application/pdf`.
- `data: LargeBinary` — the file bytes.
- `filename: str | None` — original filename.
- `created_at: datetime`.

## Media Storage (`/media` route + helper)

- `app/admin/routes.py::_save_upload` is replaced by a function that creates a
  `MediaAsset` row (reads `file.file.read()`, stores bytes + content type) and
  returns the new `asset_id`. `create_product` / `update_product` /
  gallery-image handling store `image_asset_id` / `datasheet_asset_id` /
  `ProductImage.asset_id` instead of file paths.
- New route `GET /media/{asset_id}` (public, in a new `app/api/media.py` or
  added to `products.py`): loads the `MediaAsset`, returns a `Response` with
  the stored bytes, `Content-Type: <content_type>`, and
  `Cache-Control: public, max-age=31536000, immutable`. 404 if not found.
- New helper `media_url(asset_id, legacy_path)`:
  - `asset_id` set → `f"/media/{asset_id}"`
  - else `legacy_path` set → `f"/{legacy_path}"`
  - else `None`
  Registered as a Jinja global and used by both the admin templates
  (`products.html`, `product_edit.html`) and `app/api/products.py`.
- `ponytail:` comment on `MediaAsset` — if datasheets grow to hundreds of
  multi-MB PDFs and exceed Neon's free storage, move blobs to Cloudflare R2
  (add an S3 client, keep the `media_url` seam).

## Country Identification (widget → backend)

### Widget (`static/widget.js`)
- Read country from the embedding `<script>` tag:
  `document.currentScript?.dataset.country` captured at load time (before the
  IIFE's async work) — fall back to `"CM"`.
- Append to the WebSocket URL: `/ws/{CONV_ID}?country={COUNTRY}`.

### Embed snippet (per country site)
```html
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="NG"></script>
```

### Backend WebSocket (`app/api/ws.py`)
- `customer_ws` gains `country: str = Query("CM")`.
- Validate against `COUNTRIES`; anything invalid or missing → `"CM"`.
- When creating the `Conversation` (ws.py:86), set `country=country`.
- The orchestrator (`run_stream`) still finds the conversation by
  `session_id`, so it inherits the country tag; no orchestrator signature
  change needed for this spec.

### REST (`app/api/chat.py`)
- `ChatRequest` gains `country: str | None = None` (optional; the widget uses
  the WS path, this is for other callers). If the orchestrator creates the
  conversation, it passes this through.

### Public products feed (`app/api/products.py`)
- `GET /api/products` gains `?country=` (optional).
  - with a valid country → `WHERE country IS NULL OR country = :country`
  - without / invalid → `WHERE country IS NULL` (shared catalog only)

## Admin Scoping (`app/admin/`)

### `deps.py`
- `get_current_admin` already loads the `AdminUser`; expose `.country`.
- New `scope_clause(user, Model)` → SQLAlchemy filter:
  - `user.country is None` → `sqlalchemy.true()`
  - else → `Model.country == user.country`
- New `assert_visible(user, obj)` → raise `HTTPException(404)` unless
  `user.country is None or obj.country == user.country`.

### Route changes (`routes.py`)

| Route | superadmin | country_admin |
|---|---|---|
| `GET /conversations`, `/conversations/{id}` | all | `scope_clause` / `assert_visible` |
| `GET /orders`, order status update | all | `scope_clause` / `assert_visible` |
| `GET /tickets`, close ticket | all | scoped via the linked conversation's country (join `Conversation`) |
| `GET /products` | all | `Product.country == user.country OR Product.country IS NULL` |
| `POST /products` (create) | any country (form field, optional) | `country` forced to `user.country` |
| `POST /products/{id}/edit`, `/delete`, image add/delete | any | `assert_visible`; **403 if `product.country is None`** (shared, superadmin-only) |
| `GET/POST /rules`, `/rules/{id}/delete` | ✅ (`require_superadmin`) | ❌ 403 |
| `GET/POST /users` | ✅ (already `require_superadmin`) | ❌ |
| `GET /reports`, `/reports/export` | ✅ (already `require_superadmin`) | ❌ |

- Dashboard counts: scoped by `scope_clause` too.
- Sidebar (`templates/admin/base.html`): show Rules / Users / Reports links
  only when `current_user.role == "superadmin"`.

### Order creation tool (`app/tools/`)
- New tool `create_order` (alongside the existing `ticket` tool), registered
  with the orchestrator.
- Signature (LLM-facing): `create_order(customer_name, contact, items, notes)`.
- Implementation reads `country` and `id` from the current `Conversation`
  (the tool already has a `_db` session and conversation context like
  `ticket.py` does), generates `order_number`, inserts the `Order` row with
  `status="pending"`.
- Trigger guidance in the tool description + a rule: use only when the
  customer has explicitly confirmed they want to order / be contacted to
  purchase. No payment, no stock changes.

## Account Seeding (`app/main.py`)

Replace `_seed_admin_user` with `_seed_admin_users`, run in the same lifespan
startup step:

1. Superadmin — from `ADMIN_EMAIL` / `ADMIN_PASSWORD` (unchanged), `role
   = "superadmin"`, `country = None`. Created only if that email is absent.
2. Country admins — from `SEED_COUNTRY_ADMINS`, format
   `cm:password1,ng:password2,sd:password3,ml:password4`.
   - Email derived: `{cc}-admin@restsolar.com` (lowercase cc).
   - `role = "country_admin"`, `country = CC.upper()`.
   - Each created only if its email is absent (idempotent, per-row).
   - Malformed / unknown country codes are skipped with a log line, not fatal.

The Users page still allows superadmin to add accounts ad-hoc (now persistent
under Postgres).

## Infrastructure

1. Create a Neon project (free tier). Obtain the `postgresql://…` connection
   string.
2. In the Render dashboard, set `DATABASE_URL` to that string
   (`sync: false`). Remove the hardcoded SQLite `DATABASE_URL` value from
   `render.yaml` (leave the key out, or mark `sync: false` with no value).
3. `app/db/session.py::_normalize_database_url` already converts
   `postgres://` / `postgresql://` → `postgresql+asyncpg://`. No code change.
4. First boot: `create_all` builds the full schema on the empty Neon DB, then
   `_seed_admin_users` runs. Product catalog is loaded by running `seed.py`
   (or `scripts/build_products.py` path) once against the Neon DB — chosen
   over `migrate_sqlite_to_postgres.py` because conversation history is not
   worth preserving (it has been resetting on every deploy already) and a
   fresh seed is cleaner.
5. `requirements.txt` already has `asyncpg` (added in `32c7129`).

## Testing

Existing 64 tests must continue to pass. Tests use in-memory SQLite with
`create_all` per fixture, so new nullable columns work with no test-infra
change.

New tests:
- **Country isolation:** a `country_admin` for `NG` sees only `NG`
  conversations / orders / tickets in list and detail views; a request for a
  `CM` record returns 404. A superadmin sees all.
- **Product visibility & permission:** `NG` admin sees shared (`country IS
  NULL`) products read-only and its own `NG` products editable; editing a
  shared product returns 403; creating a product as `NG` admin forces
  `country = "NG"`.
- **Order tool:** `create_order` invoked in a conversation tagged `SD`
  produces an `Order` with `country = "SD"` and the right `conversation_id`;
  `order_number` starts with `SD-`.
- **Widget country:** a WS connection with `?country=NG` creates a
  `Conversation` with `country = "NG"`; `?country=` missing or `?country=XX`
  → `"CM"`.
- **Media round-trip:** uploading an image via `create_product` stores a
  `MediaAsset`; `GET /media/{id}` returns the bytes with the correct
  `Content-Type`; `media_url` prefers `asset_id` over `path`.
- **Products feed filter:** `/api/products?country=NG` returns shared + NG
  products; `/api/products` with no param returns shared only.
- **Seeding:** `_seed_admin_users` with a `SEED_COUNTRY_ADMINS` string
  creates four `country_admin` rows with correct countries; a second run is a
  no-op; a malformed entry is skipped without raising.

## Rollout Order

1. Merge the code change (schema + scoping + order tool + media route — all
   additive with defaults, backward compatible).
2. Create the Neon database; set `DATABASE_URL` in Render.
3. Set `SEED_COUNTRY_ADMINS` in Render.
4. Deploy → startup builds schema, seeds accounts; run `seed.py` against Neon
   for the product catalog.
5. Verify all five logins and country isolation on the live site.
6. Send the four country-specific embed snippets to the country lead; each
   site swaps its `<script>` tag.

## Open Risks

- Until the deferred agent-localization spec ships, NG/SD/ML visitors receive
  Cameroon shipping/duty/contact answers.
- Neon free tier storage (~0.5 GB): fine for new uploads only; watched via the
  `MediaAsset` `ponytail:` note.
- Neon free tier compute suspends when idle; first request after idle has a
  cold-start delay stacked on Render's own free-tier spin-up.
