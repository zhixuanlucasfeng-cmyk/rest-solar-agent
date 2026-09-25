# Unified country admin: source-of-truth implementation plan

Spec: `docs/CODEX-BRIEF.md`, Task 3 option A and Definition of Done.

## Global constraints

- Postgres in `rest-solar-agent` is the single source of truth for products, stock, and all website cart orders.
- Cameroon, Mali, Nigeria, and Sudan country managers remain restricted to their own country; superadmin retains all-country visibility.
- Public endpoints accept only the existing country whitelist (`CM`, `ML`, `NG`, `SD`).
- Public product responses expose display data and stock, but never internal duty/VAT fields. Prices remain optional and the website must display “contact us” when absent.
- Product/media fetch and order creation must work cross-origin from `https://restarsolar.net`.
- Existing AI chat and optional live-agent handoff behavior must not regress.
- The static catalog may remain only as a network-failure fallback during migration; a successful backend response is authoritative, including an empty list.
- Do not deploy or push until focused tests and a final review pass.

## Task 1 — make the public product feed website-ready

Repository: `rest-solar-agent-neon`.

1. Add failing tests proving `/api/products?country=CM` returns stable product identity, normalized country ownership, stock, and absolute media URLs usable by `restarsolar.net`.
2. Extend the existing public feed with only the fields needed by the website. Preserve shared + country filtering and omit internal duty/VAT fields.
3. Keep price fields nullable; do not synthesize or guess prices.
4. Run the focused product API and admin scope/product tests.

## Task 2 — load catalog and stock from the agent backend

Repository: `camaroom-web-neon-fix`.

1. Add tests for mapping the public feed into the current card shape, including remote media URLs, category mapping, specs, nullable price, stock, and empty-authoritative responses.
2. Add a small catalog adapter module. On country selection, fetch `/api/products?country=<code>` from the live agent backend, replace the runtime catalog and inventory, then rerender filters/grid. Ignore stale responses after country switches.
3. Preserve the static catalog only if the request fails; do not merge it into a successful response.
4. Enable the cart for all four managed countries because order creation moves to the central backend. Keep OTHER on WhatsApp-only behavior.
5. Run all website unit tests.

## Task 3 — accept website cart orders in Postgres

Repository: `rest-solar-agent-neon`.

1. Add failing API tests for `POST /api/orders`: valid country and contact, non-empty items, positive integer quantities, optional session linkage, generated country-scoped order number, and invalid payload rejection.
2. Validate every ordered SKU against the selected country's visible product feed and reject unavailable/out-of-stock quantities. Decrement stock atomically on success.
   - Country-owned products use tracked stock: reject when `stock < qty` and decrement in the order transaction.
   - Shared products are the migrated global catalog and their current zero means “untracked,” not “out of stock”; allow them without decrement until explicit per-country inventory rows exist.
3. Store a readable item snapshot in the existing `Order.items`, set `Order.country`, customer/contact fields, and expose only the created order identifier/number to the caller.
4. Ensure the existing country-scoped admin orders page displays these orders.
5. Run focused order/admin scope tests.

## Task 4 — post every managed-country cart to the central backend

Repository: `camaroom-web-neon-fix`.

1. Add tests proving cart submissions include the active country and target the agent backend for CM/ML/NG/SD.
2. Replace the Cloudflare cart order endpoint with the central endpoint while preserving the WhatsApp follow-up and error UI.
3. Keep cart contents country-bound and clear only after a successful order.
4. Run all website tests.

## Task 5 — integrated verification and handoff

1. Run backend tests that do not require downloading external embedding models, all website tests, and diff checks.
2. Review both branch diffs against the Definition of Done.
3. After deployment authorization, verify in a browser against the live site: a country product appears, its stock badge changes, a cart order appears in that country's admin console, and a live-agent handoff can be answered.

## Pre-flight interface scan

| Producer task | Consumer task | Shared interface | Ruling |
|---|---|---|---|
| Task 1 | Task 2 | `GET /api/products` JSON | Preserve the existing route and add fields; the website adapter owns shape conversion. |
| Task 2 | Task 4 | runtime country and cart enablement | One country-change refresh owns catalog/stock; cart reads the same selected country. |
| Task 3 | Task 4 | `POST /api/orders` JSON | Backend schema is authoritative; website tests use the same documented payload. |
| Task 1 | Task 3 | product visibility and stock | Order validation reuses shared + selected-country visibility rules. |
| Task 3 | existing admin orders | `Order` rows | Reuse the current model and scoped admin page rather than create a second order table. |

Ruling: the full baseline suite currently attempts to download a Hugging Face model and fails in the restricted network. This is unrelated to the catalog/order work. Focused backend suites plus all non-embedding tests are the working baseline; the external-model test remains an environment limitation.
