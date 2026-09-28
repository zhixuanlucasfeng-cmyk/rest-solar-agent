# Task 3 Report — Public Order API

## Status

Implemented the public `POST /api/orders` flow and registered it with the FastAPI app. No schema migration was added.

## TDD evidence

### RED

Command:

```text
UV_CACHE_DIR=/tmp/restar-orders-uv-cache uv run --isolated --with-requirements requirements.txt pytest -q tests/test_orders_api.py
```

Result before implementation: `16 failed`. Every case reached the real ASGI app and failed because `/api/orders` was not registered (`404 Not Found`).

### GREEN

Focused order result after implementation: `16 passed`.

Regression command:

```text
UV_CACHE_DIR=/tmp/restar-orders-uv-cache uv run --isolated --with-requirements requirements.txt pytest -q tests/test_orders_api.py tests/test_products_api.py tests/test_admin_scope.py tests/test_admin_routes.py
```

Result: `57 passed, 270 warnings in 17.54s`.

The warnings are existing Python 3.13 deprecation warnings for `datetime.utcnow()` in model defaults, admin authentication, and the reused `next_order_number` helper.

## Implemented contract

- Requires a supported country (`CM`, `ML`, `NG`, or `SD`), non-blank customer name/contact, a non-empty item array, and positive integer quantities.
- Aggregates duplicate SKU quantities before validating inventory.
- Loads only shared or selected-country products using a transaction-scoped `SELECT ... FOR UPDATE` query.
- Rejects missing/cross-country SKUs with `404` and insufficient tracked stock with `409`.
- Decrements only country-owned product stock; shared catalog rows remain untracked and unchanged.
- Generates the readable item snapshot from server-side product names.
- Links a conversation only when both `session_id` and country match.
- Reuses `next_order_number`, persists a pending order, commits the order and stock update atomically, and rolls back on HTTP or database failures.
- Returns only `order_number`, `status`, and `confirmation`; no internal pricing is exposed.

## Files

- `app/api/orders.py` — new public order endpoint.
- `app/main.py` — router registration.
- `tests/test_orders_api.py` — success, validation, inventory, duplicate SKU, visibility, and session isolation coverage.

## Concerns

- `next_order_number` remains count-based as required. The endpoint now retries an order-number unique conflict up to three transaction attempts; sustained conflicts still return `409`.
- PostgreSQL enforces the row lock; SQLite accepts but does not enforce `FOR UPDATE`, so the focused test suite verifies behavior but not live PostgreSQL lock contention.

## Review fix round 1

The review identified that requests locking different product rows could concurrently calculate the same count-based order number. The losing request previously rolled back and immediately returned `409`.

Added a focused RED test that forces the first generated number to conflict with an existing order. Before the fix it returned `409`; after the fix it returns `201`, creates exactly one new order, and decrements tracked inventory exactly once.

The order transaction now retries at most three times only for SQLAlchemy `IntegrityError`. Each failed attempt rolls back, then reruns the product `SELECT ... FOR UPDATE`, stock validation, conversation lookup, number generation, and ORM object creation. HTTP errors and other exceptions are rolled back without retry.

Review-fix regression result:

```text
58 passed, 273 warnings in 17.59s
```
