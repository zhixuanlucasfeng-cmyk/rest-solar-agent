# Multi-country cutover runbook

## 1. Provision Neon Postgres

- Create a project at [neon.tech](https://neon.tech) (free tier available).
- Copy the connection string (looks like `postgresql://USER:PASS@HOST/DB?sslmode=require`).
- Keep this string secure; it will be added to Render environment variables.

## 2. Render environment

In the rest-solar-agent service → Environment, set the following:

- `DATABASE_URL` = the Neon connection string (from step 1)
- `ADMIN_EMAIL` = `admin@restsolar.com`
- `ADMIN_PASSWORD` = (generate a strong value, store in the team vault)
- `SEED_COUNTRY_ADMINS` = `cm:<pw>,ng:<pw>,sd:<pw>,ml:<pw>` (four distinct strong values, store in the team vault)
- Keep `LLM_API_KEY`, `ADMIN_SECRET_KEY`, SMTP vars as they are.

> **Rotating a country-admin password:** editing `SEED_COUNTRY_ADMINS` and redeploying does **not** change an existing password — seeding is idempotent per email and skips accounts that already exist. Rotate the password via the Users page, or with a manual DB update.

## 3. Deploy

Push the `multi-country-backend` branch → merge to `phase-2-build` → Render auto-deploys.

On boot the app will:
- Run `create_all` (builds the full schema on the empty Neon DB)
- Run `_seed_admin_users` (creates the 5 accounts: 1 superadmin + 4 country admins)

## 4. Load the product catalog (one-time)

From a shell with the Neon `DATABASE_URL` set, run:

```bash
export DATABASE_URL='postgresql://...neon...'
python seed.py                          # rules + FAQ RAG
python scripts/ingest_catalog_2026.py   # 169 shared products (country stays NULL)
```

> **RAG index caveat:** `python seed.py` writes RAG vectors to `data/chroma_db`, which `.dockerignore` excludes from the image. Running it from a local shell populates Neon's `rules` table but leaves the production instance's FAQ/RAG index empty — populating the FAQ/RAG index on the production instance is a separate step, not covered by this command.

## 5. Verify

Run the following verification checklist:

1. **Superadmin login**: Log in as `admin@restsolar.com` → see all countries in the sidebar, Rules/Users/Reports navigation visible.
2. **Nigeria admin**: Log in as `ng-admin@restsolar.com` → Conversations/Orders/Tickets empty, Products shows 169 shared (read-only), no Rules/Users/Reports in the nav.
3. **API - global products**: `curl https://rest-solar-agent.onrender.com/api/products` → returns 169 items.
4. **API - country filter**: `curl 'https://rest-solar-agent.onrender.com/api/products?country=NG'` → returns 169 items (no NG-specific yet).
5. **Widget loads**: Navigate to a country site with the widget embed (see section 6 below) → widget opens without console errors.

## 6. Widget embed snippets

Send these snippets to each country lead. They will replace their existing widget `<script>` tags with these:

**Cameroon (CM)**:
```html
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="CM"></script>
```

**Nigeria (NG)**:
```html
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="NG"></script>
```

**Sudan (SD)**:
```html
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="SD"></script>
```

**Mali (ML)**:
```html
<script src="https://rest-solar-agent.onrender.com/static/widget.js" data-country="ML"></script>
```

**Important:** The widget requires the `<script>` tag to be a plain, inline tag with the `data-country` attribute. It will NOT work if:
- The script is loaded as `type="module"`
- The script has `async` or `defer` attributes
- The script is dynamically injected by JavaScript

The widget uses `document.currentScript` to read the `data-country` attribute. If these conditions are violated, the country will silently fall back to `CM` (Cameroon).

## Known gap

Until the deferred agent-localization spec ships, the agent still answers with Cameroon shipping / duty / contact figures regardless of the `data-country` value. Country admins will see different conversation/order/product scopes, but the LLM responses will reflect Cameroon logistics and pricing until localization is complete.
