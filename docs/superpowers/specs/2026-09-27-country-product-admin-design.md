# Country Product Administration Design

## Goal

Give the Cameroon, Mali, Nigeria, and Sudan country managers a safe product-management workflow that controls what customers see on restarsolar.net. Managers can create and edit their own products, local price, stock, images, and specifications; unpublish and archive products without losing data; and use the console in English, Simplified Chinese, or French.

## Scope

This change covers product lifecycle, country-local prices, admin-console localization, and the website's product data source. It preserves the existing country isolation, order management, Inbox, live-agent handoff, and AI price-safety behavior.

The four managed countries and currencies are:

| Country | Code | Currency |
|---|---|---|
| Cameroon | CM | XAF |
| Mali | ML | XOF |
| Nigeria | NG | NGN |
| Sudan | SD | SDG |

## Product lifecycle

Each product has one `status` value:

- `active`: returned by the public API and visible on the website.
- `inactive`: deliberately taken off sale; retained in the normal admin list and reversible.
- `archived`: removed from the normal admin list and public API; visible in an Archive filter and reversible.

New products default to `active`. Existing products are migrated to `active`, so deployment does not hide the current catalogue.

Country managers can change products owned by their country between all three states. They cannot modify shared products or products belonging to another country. Superadmins can manage every product. Permanent deletion is removed from country-manager controls and restricted to superadmins, with an explicit confirmation screen or confirmation control. Gallery-image removal remains available to a product's permitted editor.

## Pricing

Country-owned products store `price_local` as a nullable decimal-like numeric value. Their public currency is derived from the product's country using the fixed map above; staff do not type arbitrary currency codes. A null price means “contact for price.”

Existing `price_cny` and `price_xaf` columns remain for compatibility during migration. For existing Cameroon products, `price_local` is initialized from `price_xaf` when available. Existing products in other countries keep a null local price until their manager sets it. Shared products do not expose a local price unless a future country-price table is introduced; that is outside this scope.

The public API returns `price_local`, `currency`, `stock`, and `status`-filtered active products only. The website displays a local price only when the selected country's product has one, otherwise it displays the existing contact-for-price message. The Gemini assistant continues to avoid promising prices; displayed catalogue prices remain subject to confirmation.

## Website synchronization

The agent backend becomes the product source of truth already chosen in the current architecture. The homepage continues using `/api/products?country=XX`. The separate `products.html` page is changed from the static `products.js` catalogue to the same country-filtered public API, with the static catalogue only as a network-failure fallback.

Consequences:

1. Setting a product to `inactive` or `archived` removes it from both product surfaces and from AI catalogue context.
2. Restoring it to `active` makes it visible again.
3. Product edits, stock, images, and local prices appear without rebuilding GitHub Pages.
4. A successful empty API response remains authoritative; it must not silently restore static products.

## Admin localization

The console supports `en`, `zh`, and `fr`. Language is selected from the header and stored in a cookie so it survives navigation and login. Invalid language values fall back to English.

Translation is server-side through a small dictionary helper exposed to Jinja as `t(key)`. Templates use stable keys for navigation, authentication, dashboard, Inbox, conversations, products, product forms, orders, tickets, users, rules, reports, buttons, product states, and common validation/error labels. Dynamic customer content, product names, SKUs, email addresses, country codes, and order data are not translated.

The language choice changes labels only; URLs, authorization, and stored business data remain unchanged.

## Database upgrade

The current service uses `Base.metadata.create_all`, which does not add columns to Neon. Startup therefore runs an idempotent additive schema upgrade before seeding:

- add `products.status` with a server default of `active` when missing;
- add `products.price_local` when missing;
- backfill null/empty status values to `active`;
- backfill Cameroon `price_local` from `price_xaf` where safe.

The upgrader detects the active SQL dialect and is tested against SQLite. PostgreSQL statements use `ADD COLUMN IF NOT EXISTS`; no destructive migration or table rewrite is allowed.

## Authorization and safety

- `agent`: Inbox and conversation history only; no product management.
- `country_admin`: manage products where `product.country == user.country`; view shared products read-only.
- `superadmin`: manage shared and country products, restore archives, and permanently delete.
- Public API: no authentication, active products only, filtered to shared plus the requested valid country.
- State-changing endpoints remain POST-only and reuse `_assert_product_writable`.

Archive and unpublish actions are reversible and should be presented as the normal controls. Permanent deletion is visually separated, superadmin-only, and never used as the ordinary way to remove a product from sale.

## UI behavior

The Products screen has tabs or filters for Active, Unpublished, and Archived. Every row shows country, local price/currency, stock, and state. Permitted editors get Edit, Unpublish/Publish, and Archive/Restore actions. Superadmins additionally get Permanent Delete.

The create/edit form shows the country currency beside the local price input. For country managers the country is fixed by their account. For superadmins the country selector determines the price currency; shared products show no country-local price input.

All controls remain usable on mobile widths, with tables allowed to scroll horizontally rather than clipping actions.

## Error handling

- Invalid product status transitions return HTTP 400.
- Missing products return HTTP 404.
- Cross-country and shared-product writes by a country manager retain the existing 403/404 behavior.
- Invalid or negative local prices and stock return HTTP 400 instead of being stored.
- Public API failures keep the website's existing country-safe static fallback and visibly mark prices as requiring confirmation.

## Testing and acceptance

Automated tests cover:

1. model defaults and additive migration;
2. public API exclusion of inactive and archived products;
3. country-manager lifecycle permissions and superadmin-only deletion;
4. local price/currency serialization for all four countries;
5. English, Chinese, and French console labels plus cookie persistence;
6. separate Products page loading the same live feed and honoring successful empty results;
7. all existing admin, country isolation, chat, order, handoff, and website tests.

Live browser acceptance checks use a disposable test product for one country: create it, see it on both website product surfaces, change its price and stock, unpublish it and confirm disappearance, archive/restore it, and switch the console across all three languages. The disposable product is archived after verification; permanent deletion is not required for the acceptance path.

## Out of scope

- Translating product names and descriptions automatically.
- Adding Arabic to the admin console.
- Changing Gemini to quote prices as guaranteed offers.
- Replacing the existing order or live-chat implementations.
- Introducing per-country variants for shared products.
