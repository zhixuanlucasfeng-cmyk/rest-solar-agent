# Restar Solar 2026 Catalog — Integration Summary

Feishu MCP/webhook is not configured in this environment, so this summary is written here instead, as requested.

## 1. Inventory (169 datasheets, 84 in Part1 + 85 in Part2)

Full table: `data/catalog_2026/INVENTORY.md`

| Category | Count |
|---|---|
| Solar Panels (光伏组件) | 99 |
| Batteries (电池) | 26 |
| Inverters (逆变器) | 19 |
| Other/Accessories (其它) | 13 |
| ESS (储能) | 6 |
| Charge Controllers (控制器) | 6 |

The zips were already organized into category subfolders matching your taxonomy exactly, which made categorization reliable.

## 2. Structured product database

`data/catalog_2026/products.json` / `products.csv` — one row per PDF with: sku, category/subcategory, model, wattage/power_kw/capacity_ah/capacity_kwh/voltage, dimensions, features (TOPCon/bifacial/full-black/dual-glass/etc.), datasheet path, product image path.

Field extraction is regex/heuristic-based (no field is invented) — a handful of "Series" overview PDFs (e.g. MPK6, RTFT charge controllers) don't have machine-extractable amperage in text and are left blank; the full PDF is still attached and searchable.

## 3. Website / product data (extended existing system, per your decision)

Since `rest-solar-agent` is a chat widget + admin backend (no public catalog pages existed), I extended the existing architecture rather than building a new site:

- **`Product` DB model** (`app/db/models.py`) got 14 new columns: category, subcategory, model, wattage, power_kw, capacity_ah, capacity_kwh, voltage, dimensions, features, datasheet_path, image_path, featured, use_cases. `price_cny`/`price_xaf` are now nullable ("price on request").
- All 169 products ingested (`scripts/ingest_catalog_2026.py`, idempotent/rerunnable). 75 flagged `featured=True` covering your 7 Cameroon-priority segments (high-watt TOPCon panels, LiFePO4 batteries, business ESS, shop fridges, street lights, borehole pumps).
- **Admin product page** (`templates/admin/products.html`) now shows category filter tabs, product thumbnail, specs, featured badge, and a datasheet download link per product.
- **Datasheets**: stored at `static/datasheets/{SKU}.pdf`, served automatically via the existing `/static` mount. **Switched to lossless compression per your request** (Ghostscript `/prepress`, image downsampling disabled — no quality/resolution loss, just stream and font-table optimization). Total size: ~984MB → **290MB** (a 70% reduction with zero visual degradation). Since nothing is downsampled, only 44/169 land under 1MB naturally; the rest range roughly 1–9MB depending on how image-heavy the original datasheet was. (Earlier in this session I'd also tried an aggressive lossy pass that hit <1MB on 91% of files — abandoned per your instruction to avoid lossy compression.)
- **Product images**: extracted from each PDF's largest embedded image, stored at `static/product_images/{SKU}.jpg`.

## 4. AI knowledge base — important fix, then a course-correction

While wiring this up I found that **`app/rag/embedder.py` / `app/rag/retriever.py` (the ChromaDB RAG pipeline) were never actually called from the chat pipeline** — `orchestrator.py` used a hardcoded FAQ string, so `seed.py`'s embeddings were dead weight. This predates my changes.

**My first fix was wrong and I caught it before committing.** I wired `orchestrator.py` to embed each message with the local `sentence-transformers` model and query ChromaDB. Before committing, I checked `git log` and found commit `8c88b34` ("fix: remove torch/sentence-transformers to fix OOM on 512MB free tier") — this was a *deliberate* prior fix: PyTorch adds 300-400MB RAM and crashed Render's free tier on every chat request, so `torch`/`sentence-transformers`/`chromadb` were removed from `requirements.txt` entirely. My local `.venv` still had them installed (stale leftover), so local tests passed, but deploying my change as-is would have `ImportError`'d on Render (packages not in `requirements.txt`) — worse than the original OOM.

**Corrected approach**: `orchestrator.py` now does plain keyword/tag matching against the `products` table directly via the existing SQLAlchemy session — no embeddings, no new dependencies. It tokenizes the user's message, scores products by model/SKU mention, field token overlap, and use-case tag match, plus lightweight numeric-threshold parsing (e.g. "above 500W") so wattage-range questions work. Verified `app.main`'s full import graph loads with zero `torch`/`chromadb`/`sentence_transformers`/`app.rag` modules.

`scripts/ingest_catalog_rag.py` and the ChromaDB collection still exist (harmless, ~5MB, gitignored) as **optional tooling** if you ever move to a paid Render tier with more RAM — they are not called by the running app.

Verified live against the running server (with the corrected, dependency-free retrieval):
- EN: "What TOPCon solar panels above 500W do you have?" → correctly cites RT8H-M (SP-009, 510-535W) and RT8H-M-BD (SP-010, bifacial TOPCon, 595-630W).
- FR: "Je cherche une solution pour pomper de l'eau depuis un forage" → correctly recommends "Solar Pump Inverter" (INV-074) + "DC water pump" (OTH-139) by name and SKU.
- EN: LiFePO4 battery capacity question → cites real SKUs/capacities, no invented prices (says "contact for quote", per your `no_invented_prices` rule).

Also updated the general FAQ seed text (`data/seeds/faqs_en.txt` / `faqs_fr.txt`) — the old panel range ("50W-550W") was outdated against the new catalog (3W-750W).

**Second bug found+fixed during this verification**: 19 products (mostly the "其它"/other accessories — water pumps, freezers, street lights — plus a few battery/inverter entries) had their `model` field truncated to a single generic English word by an over-eager regex (e.g. "Solar Pump Inverter" → "Solar", "DC water pump" → "DC", "Wall Mounted LiFePO₄ Battery..." → "Wall"). This made both the admin product list and the chatbot's context useless for those items. Fixed by falling back to the full PDF title for any product whose extracted model matched a blocklist of bare dictionary words. `data/catalog_2026/products.json/.csv/INVENTORY.md` and the DB were all re-generated after the fix.

## 5. Verification

- `pytest`: **64/64 passed**, no regressions from the schema/orchestrator changes.
- App boots cleanly (`uvicorn app.main:app`), `/health`, `/chat`, `/admin/login` all return 200.
- Static file serving confirmed for both datasheets and product images.
- Your existing 15 conversations and all other tables were untouched — I only dropped/recreated the (empty, 0-row) `products` table, with an explicit safety check and your confirmation first.

## Things to decide / know about

1. **Repo size**: the new `static/datasheets/` (290MB, lossless) + `static/product_images/` (16MB) add ~306MB of binary files. That's substantial for a plain git repo (and for Render's free-tier git-based deploys). Consider Git LFS or moving datasheets to object storage (S3/R2) — I didn't want to make that infrastructure call unilaterally. Committed as regular git objects for now, per your instruction.
2. **Pre-existing uncommitted work** in `app/llm/client.py` (streaming tool-call rework, noted in earlier sessions) is still there and untouched by me — separate from this catalog work.
3. **`app/rag/` (ChromaDB + embedder) is intentionally not used at runtime** — see section 4. Don't re-wire it into `orchestrator.py` without also re-adding `torch`/`sentence-transformers`/`chromadb` to `requirements.txt` AND upgrading past the 512MB free tier, or it will crash/fail to boot on Render again.

## Files changed/added
```
Modified: app/admin/routes.py, app/agent/orchestrator.py, app/db/models.py,
          templates/admin/products.html, data/seeds/faqs_en.txt, data/seeds/faqs_fr.txt,
          data/rest_solar.db, data/chroma_db/*
New:      data/catalog_2026/ (products.json, products.csv, INVENTORY.md)
          static/datasheets/ (169 compressed PDFs)
          static/product_images/ (169 extracted product photos)
          scripts/migrate_products_2026.py
          scripts/ingest_catalog_2026.py
          scripts/ingest_catalog_rag.py
```

## To re-run (idempotent)
```bash
PYTHONPATH=. .venv/bin/python3 scripts/migrate_products_2026.py   # only if products table is empty
PYTHONPATH=. .venv/bin/python3 scripts/ingest_catalog_2026.py
PYTHONPATH=. .venv/bin/python3 scripts/ingest_catalog_rag.py
```
