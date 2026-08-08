# Fast-Path Responder Design

**Goal:** Cut perceived reply latency for the subset of customer questions that have a single, deterministic, database-backed answer — by answering them without an LLM round trip at all — while leaving every other question exactly on today's LLM streaming path.

**Architecture:** A new intent-matching module runs synchronously at the very top of `orchestrator.run()` and `orchestrator.run_stream()`, before any LLM call is constructed. If it returns a confident match, the reply is built from a template + database fields, persisted to the conversation history exactly like an LLM reply, and returned/streamed immediately (tens of milliseconds). If it returns no match — including any ambiguous, compound, or low-confidence case — control falls through unchanged into the existing LLM pipeline. The LLM path itself is not modified.

## Why Not Everything Is Fast-Pathed

Two live-data checks against `data/rest_solar.db` (2026-08-08, 169 products) shaped the scope:

- `stock` is `0` for all 169 products — it is an unpopulated default, not real inventory data. Fast-pathing stock questions today would tell every customer "out of stock," which is worse than the current LLM behavior. **Stock questions are excluded from v1.**
- `price_xaf` is populated for only 8 of 169 products. Price fast-pathing is scoped to just those 8; the other 161 fall through to the LLM, which already replies "Price on request" for unpriced items (`orchestrator.py`'s `_retrieve_catalog_context`) — unchanged behavior.
- `wattage`/`power_kw`/`capacity_ah`/`capacity_kwh` is populated for 150 of 169 products (via the 2026 PDF spec-extraction work) — spec questions are the widest-coverage fast-path category.

## In Scope for v1 (Fast-Pathed)

Each requires a single, unambiguous intent match. Any ambiguity (multiple candidate products with close scores, a compound question, an unrecognized phrasing) falls through to the LLM — there is no partial or best-effort fast-path reply.

1. **Static FAQ topics** (bilingual EN/FR, text already exists verbatim in `orchestrator.py`'s `_FAQ_CONTENT`): panel size range, battery warranty terms, delivery outside Douala, China shipment lead time, Cameroon import duty/VAT.
2. **Contact info requests** (already exists as `_CONTACT_INFO`).
3. **Single-product spec questions** (wattage/power/capacity/voltage/dimensions) — for the 150/169 products with spec data.
4. **Single-product price questions** — for the 8/169 products with `price_xaf` set.

## Explicitly Out of Scope for v1

- Stock/availability questions (data not trustworthy yet — needs a real inventory fix first, separate effort).
- Order/purchase intent — stays on the LLM path, which already routes to WhatsApp via the `order_to_whatsapp` rule.
- Comparison/recommendation/open-ended questions ("what do you recommend for my situation") — inherently need LLM reasoning.
- Any case where product-match confidence is ambiguous.

## Components

- **New file: `app/agent/fast_path.py`**
  - `try_fast_path(message: str, lang: str, db: AsyncSession) -> str | None` — the single entry point. Returns a ready-to-send reply string, or `None` if nothing matched confidently.
  - Reuses the existing per-product scoring logic already in `orchestrator.py`'s `_retrieve_catalog_context` (tokenized keyword overlap + model/SKU exact-match boost) rather than duplicating it — that function is extracted into a shared helper both `fast_path.py` and `orchestrator.py` import, so scoring behavior for the LLM's catalog-context injection and the fast-path's product matching never drifts apart.
  - Bilingual (EN/FR) regex/keyword intent classifiers for each of the 4 categories above, modeled on the existing `_FR_RE` pattern style in `language_detector.py`.
  - A confidence gate: product-question fast-paths require the top-scoring product to beat the second-best by a clear margin (exact model/SKU mention, or the only product scoring above zero) — anything closer falls through.

- **Modified: `app/agent/orchestrator.py`**
  - `run()`: after `lang = detect_language(message)` and conversation lookup/creation, call `try_fast_path`. On a hit: persist the user + assistant `Message` rows, `commit()`, and `return {"reply": ..., "language": lang}` — skipping rule-matching, catalog-context building, and the LLM call entirely.
  - `run_stream()`: same check, same persistence; on a hit, `yield` the full reply as one chunk (the client-side streaming UI already handles arbitrary chunk boundaries, so a single-chunk "stream" needs no client change) and `return` before opening the LLM stream.
  - The extracted scoring helper (see above) is the only other change to this file; the LLM call sites, system prompt, and rule-engine integration are untouched.

## Data Flow

```
message ─▶ detect_language ─▶ try_fast_path(message, lang, db)
                                     │
                         match, high confidence?
                            │                │
                           yes               no
                            │                │
                   build reply from    (existing path,
                   DB fields/FAQ text   unchanged: rules,
                            │           catalog_context,
                   persist + return/     system prompt,
                   yield immediately     LLM stream call)
```

## Error Handling & Edge Cases

- `try_fast_path` must never raise past the caller — any internal error (bad regex state, missing field) is caught inside it and treated as "no match," falling through to the LLM path rather than breaking the request. This mirrors the existing `LLMUnavailableError` philosophy: a fast-path bug degrades to today's behavior, never to a worse one.
- A product with `price_xaf = None` matched by a price-intent question is *not* a fast-path hit — it must fall through, both because the "Price on request" phrasing is more than a raw field substitution and because keeping that message in exactly one place (the LLM's existing catalog context) avoids two copies drifting apart.
- Multi-intent messages ("what's the price and warranty on the 330W panel") are not decomposed — a message must match exactly one category confidently to fast-path; mixed intent falls through.
- Fast-path replies still go through the same house style already enforced in the LLM's system prompt (short, plain sentences, no markdown/tables) — templates are written to match, not left to vary.

## Testing

- **`tests/test_fast_path.py`** (new): unit tests per intent category, in both English and French — hits (with expected reply content) and near-misses that must return `None` (ambiguous product match, unrecognized phrasing, stock question, compound question, order intent). Includes the two boundary cases the live-data check surfaced: a spec question on a product with no spec data (→ `None`), and a price question on one of the 161 unpriced products (→ `None`).
- **`orchestrator.py` integration tests** (extend existing `tests/test_orchestrator.py`): mock the LLM client and assert it is *not* called when a fast-path hit occurs, and *is* called unchanged when it doesn't — for both `run()` and `run_stream()`.
