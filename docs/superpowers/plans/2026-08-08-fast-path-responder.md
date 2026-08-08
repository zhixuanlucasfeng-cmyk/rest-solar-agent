# Fast-Path Responder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer a narrow set of high-confidence, deterministic customer questions (FAQ topics, contact info, single-product specs, single-product prices) directly from the database in `app/agent/orchestrator.py`'s `run()`/`run_stream()`, bypassing the Gemini LLM call entirely — cutting reply latency from ~1-3s to tens of milliseconds for that subset, with zero behavior change for every other question.

**Architecture:** A new `try_fast_path(message, lang, db)` function runs at the top of `run()`/`run_stream()`, before any LLM call is built. A confident match short-circuits straight to persisting + returning/yielding the reply. No match (including anything ambiguous) falls through unchanged into the existing LLM pipeline. The per-product keyword-scoring logic already living inside `orchestrator._retrieve_catalog_context` is extracted into a shared module so the LLM's catalog-context text and the fast-path's product matching use one scoring implementation, never two that can drift apart.

**Tech Stack:** Python 3, SQLAlchemy async ORM, pytest + pytest-asyncio (`asyncio_mode = auto` per `pytest.ini`), existing `AsyncMock`/`@patch` test conventions from `tests/test_orchestrator.py`.

## Global Constraints

- No fast-path category may fire on ambiguous input. If more than one intent category matches, or more than one product is a plausible match, the function returns `None` and the caller falls through to the existing LLM path — there is no partial/best-effort fast-path reply.
- Reply templates must match the house style already enforced in `orchestrator.py`'s `_SYSTEM_TEMPLATE`: short plain sentences, no markdown, no tables/headers/bullet lists.
- FAQ and contact-info reply text must be copied verbatim (translated meaning already correct) from the existing `_FAQ_CONTENT`/`_CONTACT_INFO` strings in `app/agent/orchestrator.py` — do not rewrite or re-translate them.
- Stock/availability questions are explicitly out of scope (the `stock` column is `0` for all 169 products today — not real inventory data; fast-pathing it would tell every customer "out of stock").
- Price fast-path only fires when `Product.price_xaf` is set (true for 8 of 169 products as of 2026-08-08); everything else must fall through to the LLM's existing "Price on request" behavior in `_retrieve_catalog_context` — do not duplicate that message in the fast path.
- The existing LLM call sites (`chat_complete`, `chat_complete_stream`), the system prompt, and the rule-engine integration in `orchestrator.py` are not modified by this plan except for the two early-return insertions described in Task 2.
- Every task in this plan must leave the full existing test suite green (`pytest` from the repo root) in addition to its own new tests.

---

## File Structure

- **New: `app/agent/catalog_match.py`** — the product-scoring logic extracted from `orchestrator._retrieve_catalog_context` (tokenizing, watt-threshold parsing, use-case keyword matching, `score_products()`), plus a new `format_specs()` helper and a new `top_confident_match()` helper. Both `orchestrator.py` and the new `fast_path.py` import from here.
- **Modified: `app/agent/orchestrator.py`** — `_retrieve_catalog_context` calls the extracted `score_products`/`format_specs` instead of inlining the logic; `run()` and `run_stream()` each gain one early call to `try_fast_path`.
- **New: `app/agent/fast_path.py`** — `try_fast_path(message, lang, db) -> str | None`, the bilingual intent classifiers, and the FAQ/contact reply text table.
- **New: `tests/test_catalog_match.py`** — unit tests for the extracted scoring module (pure logic, no DB).
- **New: `tests/test_fast_path.py`** — unit tests per fast-path intent category, English and French, hits and near-misses.
- **Modified: `tests/test_orchestrator.py`** — integration tests asserting the LLM is/isn't called depending on fast-path outcome, for both `run()` and `run_stream()`.

---

### Task 1: Extract shared catalog-scoring helper

**Files:**
- Create: `app/agent/catalog_match.py`
- Modify: `app/agent/orchestrator.py:1-143` (imports + `_retrieve_catalog_context`)
- Test: `tests/test_catalog_match.py`

**Interfaces:**
- Produces: `score_products(message: str, products: list[Product]) -> list[tuple[int, Product]]` — full sorted-descending list of `(score, product)` pairs with `score > 0` (no truncation; callers slice). `format_specs(p: Product) -> str` — the comma-joined spec string (wattage/power/capacity/voltage/dimensions). `top_confident_match(scored: list[tuple[int, Product]]) -> Product | None` — returns the top product if it is the sole match, or leads the runner-up by at least 5 points; otherwise `None`.
- Consumes (Task 2+): both new helpers, by `app/agent/fast_path.py`.

This task is a behavior-preserving refactor — no functional change to `_retrieve_catalog_context`'s output.

- [ ] **Step 1: Write the failing test for `score_products`**

```python
# tests/test_catalog_match.py
from app.db.models import Product
from app.agent.catalog_match import score_products, format_specs, top_confident_match


def _panel(**overrides):
    defaults = dict(
        name="Test Panel", sku="SP-TEST-1", category="solar_panels",
        model="RTM210M", wattage="210W",
    )
    defaults.update(overrides)
    return Product(**defaults)


def test_score_products_ranks_exact_model_mention_highest():
    exact = _panel(model="RTM210M", sku="SP-100")
    other = _panel(model="RTM330M", sku="SP-200", wattage="330W")
    scored = score_products("How much is the RTM210M panel?", [exact, other])
    assert scored[0][1] is exact
    assert scored[0][0] >= 5


def test_score_products_excludes_zero_score_products():
    p = _panel(model="RTM210M", category="solar_panels", wattage="210W")
    scored = score_products("What's the weather like today?", [p])
    assert scored == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_catalog_match.py -v`
Expected: `ModuleNotFoundError: No module named 'app.agent.catalog_match'`

- [ ] **Step 3: Create `app/agent/catalog_match.py` by extracting the existing logic**

```python
"""Product-matching logic shared by orchestrator.py's LLM catalog-context
text and fast_path.py's deterministic product answers — kept in one place
so the two never score the same message differently.
"""
import re

from app.db.models import Product

_USE_CASE_KEYWORDS = {
    "home_backup": ["home", "house", "backup", "outage", "blackout", "maison", "coupure", "résidentiel", "secours"],
    "shop_fridge": ["fridge", "freezer", "refrigerat", "shop", "cold", "congélateur", "réfrigérat", "boutique", "froid"],
    "borehole_pump": ["pump", "borehole", "well", "water", "forage", "pompe", "puits", "eau"],
    "street_lighting": ["street light", "streetlight", "flood light", "lighting", "lampadaire", "éclairage", "lumière"],
    "business_ess": ["business", "commercial", "factory", "hotel", "entreprise", "usine", "hôtel", "ess", "smartcube"],
}

_ABOVE_WORDS = r"above|over|more than|greater than|at least|plus de|au moins|au-dessus de"
_BELOW_WORDS = r"below|under|less than|fewer than|moins de|en dessous de"
_WATT_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*w", re.I)
_WATT_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*w\b", re.I)


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _parse_watt_range(wattage_str: str | None) -> tuple[float, float] | None:
    if not wattage_str:
        return None
    m = _WATT_RANGE_RE.search(wattage_str)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _WATT_SINGLE_RE.search(wattage_str)
    if m:
        return float(m.group(1)), float(m.group(1))
    return None


def _parse_watt_threshold(message: str) -> tuple[str, float] | None:
    """Detect '>500W'-style thresholds in the message: ('above'|'below', watts)."""
    for direction, words in (("above", _ABOVE_WORDS), ("below", _BELOW_WORDS)):
        m = re.search(rf"(?:{words})\s*(\d+(?:\.\d+)?)\s*w?\b", message, re.I)
        if m:
            return direction, float(m.group(1))
    return None


def score_products(message: str, products: list[Product]) -> list[tuple[int, Product]]:
    """Score every product against the message; return (score, product) pairs
    with score > 0, sorted descending. Callers slice for their own top-N need."""
    msg_lower = message.lower()
    tokens = _tokenize(message)

    matched_use_cases = {
        tag for tag, kws in _USE_CASE_KEYWORDS.items() if any(kw in msg_lower for kw in kws)
    }
    watt_threshold = _parse_watt_threshold(message)

    scored: list[tuple[int, Product]] = []
    for p in products:
        score = 0
        haystack = " ".join(filter(None, [
            p.model, p.category, p.subcategory, p.wattage, p.power_kw,
            p.capacity_ah, p.capacity_kwh, p.voltage, p.features,
        ])).lower()
        if p.model and p.model.lower() in msg_lower:
            score += 5
        if p.sku and p.sku.lower() in msg_lower:
            score += 5
        haystack_tokens = _tokenize(haystack)
        score += len(tokens & haystack_tokens)
        if p.use_cases:
            product_use_cases = {t.strip() for t in p.use_cases.split(",") if t.strip()}
            score += 2 * len(matched_use_cases & product_use_cases)

        if watt_threshold and score > 0:
            direction, threshold = watt_threshold
            watt_range = _parse_watt_range(p.wattage) or _parse_watt_range(p.power_kw)
            if watt_range:
                lo, hi = watt_range
                meets = (hi >= threshold) if direction == "above" else (lo <= threshold)
                score += 4 if meets else -4

        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def format_specs(p: Product) -> str:
    """Comma-joined spec string, or "" if the product has no spec data."""
    return ", ".join(filter(None, [
        p.wattage, p.power_kw, p.capacity_ah, p.capacity_kwh,
        f"voltage {p.voltage}" if p.voltage else None,
        f"dimensions {p.dimensions}" if p.dimensions else None,
    ]))


def top_confident_match(scored: list[tuple[int, Product]]) -> Product | None:
    """The top scorer, but only if unambiguous: either it's the sole match,
    or it leads the runner-up by at least 5 points (the same margin an exact
    model/SKU mention is worth) — otherwise None."""
    if not scored:
        return None
    if len(scored) == 1:
        return scored[0][1]
    if scored[0][0] - scored[1][0] >= 5:
        return scored[0][1]
    return None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_catalog_match.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Add the confidence-gate boundary test**

```python
# tests/test_catalog_match.py (append)
def test_top_confident_match_none_when_ambiguous():
    a = _panel(model="RTM210M", sku="SP-100", wattage="210W", category="solar_panels")
    b = _panel(model="RTM220M", sku="SP-101", wattage="220W", category="solar_panels")
    # Neither model/sku is mentioned by name — both score purely on shared
    # category tokens, so they tie and neither should win confidently.
    scored = score_products("Tell me about your solar panels", [a, b])
    assert top_confident_match(scored) is None


def test_top_confident_match_wins_on_exact_model():
    a = _panel(model="RTM210M", sku="SP-100", wattage="210W", category="solar_panels")
    b = _panel(model="RTM220M", sku="SP-101", wattage="220W", category="solar_panels")
    scored = score_products("How much is the RTM210M?", [a, b])
    assert top_confident_match(scored) is a


def test_format_specs_empty_when_no_spec_fields():
    p = _panel(wattage=None, power_kw=None, capacity_ah=None, capacity_kwh=None, voltage=None, dimensions=None)
    assert format_specs(p) == ""
```

Run: `pytest tests/test_catalog_match.py -v`
Expected: PASS (5/5)

- [ ] **Step 6: Point `orchestrator.py` at the extracted helpers**

In `app/agent/orchestrator.py`:
- Delete `_USE_CASE_KEYWORDS`, `_tokenize`, `_ABOVE_WORDS`, `_BELOW_WORDS`, `_WATT_RANGE_RE`, `_WATT_SINGLE_RE`, `_parse_watt_range`, `_parse_watt_threshold` (now living in `catalog_match.py`).
- Add import: `from app.agent.catalog_match import score_products, format_specs`
- Replace the body of `_retrieve_catalog_context` (the scoring loop) with a call to `score_products`, keeping only the top-N slicing and text formatting:

```python
async def _retrieve_catalog_context(message: str, db: AsyncSession) -> str:
    """Keyword-match the user's message against the products table and
    return a compact text block for the top-scoring products, or "" if
    nothing scores above zero."""
    result = await db.execute(select(Product))
    products = result.scalars().all()
    if not products:
        return ""

    scored = score_products(message, products)
    top = scored[:CATALOG_N_RESULTS]
    if not top:
        return ""

    lines = []
    for _, p in top:
        specs = format_specs(p)
        feats = f" Features: {p.features}." if p.features else ""
        price_bit = (
            f"{p.price_xaf:,.0f} FCFA each (Douala, single-unit retail price)."
            if p.price_xaf
            else "Price on request — datasheet available."
        )
        lines.append(
            f"- {p.model} ({p.category}{'/' + p.subcategory if p.subcategory else ''}, SKU {p.sku}): "
            f"{specs}.{feats} {price_bit}"
        )
    return "2026 catalog matches for this question:\n" + "\n".join(lines)
```

- [ ] **Step 7: Run the full existing suite to confirm the refactor is behavior-preserving**

Run: `pytest -v`
Expected: PASS, same count as before this task (this is a pure refactor — `test_catalog_context_shows_real_price_when_set` and `test_catalog_context_falls_back_when_price_unset` in `tests/test_orchestrator.py` must still pass unchanged, proving `_retrieve_catalog_context`'s output didn't change).

- [ ] **Step 8: Commit**

```bash
cd /Users/lucasfeng/rest-solar-agent
git add app/agent/catalog_match.py app/agent/orchestrator.py tests/test_catalog_match.py
git commit -m "Extract product-scoring logic into shared catalog_match module"
```

---

### Task 2: FAQ + contact-info fast path, wired into run() and run_stream()

**Files:**
- Create: `app/agent/fast_path.py`
- Modify: `app/agent/orchestrator.py` (`run()`, `run_stream()`)
- Test: `tests/test_fast_path.py`, `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: nothing from Task 1 yet (FAQ/contact categories don't need product scoring — that's Tasks 3-4).
- Produces: `try_fast_path(message: str, lang: str, db: AsyncSession) -> str | None` — the single entry point `orchestrator.py` calls. Returns `None` for anything not confidently matched.

- [ ] **Step 1: Write the failing tests for FAQ/contact intent matching**

```python
# tests/test_fast_path.py
import pytest
from app.agent.fast_path import try_fast_path


@pytest.mark.asyncio
async def test_panel_sizes_faq_english(db):
    reply = await try_fast_path("What panel sizes do you sell?", "en", db)
    assert reply is not None
    assert "50W to 550W" in reply


@pytest.mark.asyncio
async def test_panel_sizes_faq_french(db):
    reply = await try_fast_path("Quelles tailles de panneaux solaires vendez-vous ?", "fr", db)
    assert reply is not None
    assert "50W à 550W" in reply


@pytest.mark.asyncio
async def test_battery_warranty_faq(db):
    reply = await try_fast_path("What warranty do your batteries come with?", "en", db)
    assert reply is not None
    assert "2-year warranty" in reply


@pytest.mark.asyncio
async def test_contact_info(db):
    reply = await try_fast_path("What's your WhatsApp number?", "en", db)
    assert reply is not None
    assert "681 105 611" in reply


@pytest.mark.asyncio
async def test_no_match_falls_through(db):
    reply = await try_fast_path("What system would you recommend for my restaurant?", "en", db)
    assert reply is None


@pytest.mark.asyncio
async def test_ambiguous_multi_intent_falls_through(db):
    reply = await try_fast_path("What's the warranty and what sizes of panels do you have?", "en", db)
    assert reply is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_fast_path.py -v`
Expected: `ModuleNotFoundError: No module named 'app.agent.fast_path'`

- [ ] **Step 3: Create `app/agent/fast_path.py` with the FAQ/contact categories**

```python
"""Fast-path responder: answers a narrow set of high-confidence,
deterministic customer questions directly, bypassing the LLM entirely.

See docs/superpowers/specs/2026-08-08-fast-path-responder-design.md.

Every classifier below is deliberately conservative: a message must match
exactly one category, or it falls through to the existing LLM path (return
None). There is no partial or best-effort fast-path reply.
"""
import re

from sqlalchemy.ext.asyncio import AsyncSession

# Text copied verbatim from orchestrator.py's _FAQ_CONTENT / _CONTACT_INFO —
# do not rewrite or re-translate; keep both in sync if that source text ever
# changes.
_FAQ_REPLIES: dict[str, dict[str, str]] = {
    "panel_sizes": {
        "en": "We stock monocrystalline solar panels ranging from 50W to 550W. Our most popular sizes for homes are the 200W and 330W panels, while the 450W and 550W panels are preferred for businesses and borehole pumping systems.",
        "fr": "Nous proposons des panneaux solaires monocristallins de 50W à 550W. Les tailles les plus populaires pour les foyers sont les panneaux 200W et 330W, tandis que les panneaux 450W et 550W sont privilégiés pour les entreprises et les systèmes de pompage de forage.",
    },
    "battery_warranty": {
        "en": "Our lithium LiFePO4 batteries carry a 2-year warranty against manufacturing defects. Tubular gel batteries carry a 1-year warranty. All warranty claims must be accompanied by proof of purchase and installation documentation.",
        "fr": "Nos batteries lithium LiFePO4 bénéficient d'une garantie de 2 ans contre les défauts de fabrication. Les batteries tubulaires gel bénéficient d'une garantie d'un an. Toute demande de garantie doit être accompagnée d'un justificatif d'achat et d'une documentation d'installation.",
    },
    "delivery_outside_douala": {
        "en": "Yes, we deliver across Cameroon including Yaoundé, Bafoussam, Bamenda, Garoua, Maroua, Bertoua, and all major cities. Delivery times and costs vary by location. Contact us for a quote specific to your area.",
        "fr": "Oui, nous livrons partout au Cameroun, notamment à Yaoundé, Bafoussam, Bamenda, Garoua, Maroua, Bertoua et dans toutes les grandes villes. Les délais et frais de livraison varient selon la localisation. Contactez-nous pour un devis adapté à votre zone.",
    },
    "china_shipment_time": {
        "en": "Sea freight from our factory in China to Douala port typically takes 30 to 45 days, depending on vessel schedules and port clearance. We also offer faster air freight for urgent orders, which takes 7 to 10 days at higher cost.",
        "fr": "Le fret maritime depuis notre usine en Chine jusqu'au port de Douala prend généralement 30 à 45 jours, selon les plannings des navires et le dédouanement. Nous proposons également le fret aérien pour les commandes urgentes, avec un délai de 7 à 10 jours, à un coût plus élevé.",
    },
    "import_duty": {
        "en": "As of our most recent information, solar panels are classified under HS code 8541.40 and attract a 10% import duty plus 19.25% VAT on the CIF value. These rates can change — always verify with a licensed customs broker before importing.",
        "fr": "Selon nos dernières informations, les panneaux solaires sont classés sous le code SH 8541.40 et sont soumis à 10 % de droits d'importation plus 19,25 % de TVA sur la valeur CAF. Ces taux peuvent évoluer — vérifiez toujours auprès d'un transitaire agréé avant toute importation.",
    },
    "contact_info": {
        "en": "You can reach us on WhatsApp: Luc Su +237 681 105 611 (Cameroon) or Tom Yang +86 187 0773 7002 (China). Our showroom is at Rue Léman, Douala, Cameroon.",
        "fr": "Vous pouvez nous contacter sur WhatsApp : Luc Su +237 681 105 611 (Cameroun) ou Tom Yang +86 187 0773 7002 (Chine). Notre showroom se trouve Rue Léman, Douala, Cameroun.",
    },
}

# Each pattern is matched case-insensitively against the raw message. A
# message must hit exactly one topic across this whole table (FAQ topics
# plus product-intent keywords added in later tasks) to fast-path.
_FAQ_TRIGGERS: dict[str, re.Pattern] = {
    "panel_sizes": re.compile(
        r"panel siz|what wattages|sizes? (do|of) (you|your) panel|"
        r"taille de panneau|tailles de panneaux|quelles tailles",
        re.I,
    ),
    "battery_warranty": re.compile(
        r"(warranty|guarantee).{0,20}batter|batter.{0,20}(warranty|guarantee)|"
        r"garantie.{0,20}batterie|batterie.{0,20}garantie",
        re.I,
    ),
    "delivery_outside_douala": re.compile(
        r"deliver.{0,15}(outside|other cit|yaound)|ship.{0,15}outside douala|"
        r"livr(ez|aison).{0,20}(en dehors|hors de douala)",
        re.I,
    ),
    "china_shipment_time": re.compile(
        r"(shipment|shipping|freight).{0,20}(from china|china take)|how long.{0,20}china|"
        r"(exp[ée]dition|fret).{0,20}chine|combien de temps.{0,20}chine",
        re.I,
    ),
    "import_duty": re.compile(
        r"import (duty|tax)|customs duty|hs code|duty on solar|"
        r"droits? d'importation|droit de douane|taxe d'importation|code sh",
        re.I,
    ),
    "contact_info": re.compile(
        r"(phone|whatsapp) number|how (do|can) i (reach|contact) you|your address|"
        r"showroom address|num[ée]ro (de t[ée]l[ée]phone|whatsapp)|vous contacter|votre adresse",
        re.I,
    ),
}


def _classify_faq(message: str) -> str | None:
    """Return the single matching FAQ/contact topic key, or None if zero or
    more than one topic matched (ambiguous — must fall through)."""
    hits = [topic for topic, pattern in _FAQ_TRIGGERS.items() if pattern.search(message)]
    if len(hits) == 1:
        return hits[0]
    return None


async def try_fast_path(message: str, lang: str, db: AsyncSession) -> str | None:
    """Return a ready-to-send reply for a confidently-matched deterministic
    question, or None to fall through to the existing LLM pipeline."""
    reply_lang = "fr" if lang == "fr" else "en"

    topic = _classify_faq(message)
    if topic:
        return _FAQ_REPLIES[topic][reply_lang]

    return None
```

- [ ] **Step 4: Run to verify the FAQ/contact tests pass**

Run: `pytest tests/test_fast_path.py -v`
Expected: PASS (6/6)

- [ ] **Step 5: Wire `try_fast_path` into `orchestrator.run()`**

In `app/agent/orchestrator.py`, add the import:
```python
from app.agent.fast_path import try_fast_path
```

Immediately after conversation lookup/creation in `run()` (right after the `if not conv:` block, before `rule_bodies = await get_matching_rules(...)`), insert:

```python
    fast_reply = await try_fast_path(message, lang, db)
    if fast_reply is not None:
        db.add(Message(conversation_id=conv.id, role="user", content=message))
        db.add(Message(conversation_id=conv.id, role="assistant", content=fast_reply))
        await db.commit()
        return {"reply": fast_reply, "language": lang}
```

- [ ] **Step 6: Wire `try_fast_path` into `orchestrator.run_stream()`**

At the same point in `run_stream()` (after conversation lookup/creation, before `rule_bodies = await get_matching_rules(...)`), insert:

```python
    fast_reply = await try_fast_path(message, lang, db)
    if fast_reply is not None:
        db.add(Message(conversation_id=conv.id, role="user", content=message))
        db.add(Message(conversation_id=conv.id, role="assistant", content=fast_reply))
        await db.commit()
        yield fast_reply
        return
```

- [ ] **Step 7: Write the integration tests proving the LLM is skipped on a hit and called unchanged on a miss**

```python
# tests/test_orchestrator.py (append)
from app.agent.orchestrator import run_stream


@patch("app.agent.orchestrator.chat_complete")
async def test_fast_path_hit_skips_llm(mock_llm, db_with_rules):
    result = await run("What panel sizes do you sell?", "session-fp-1", db_with_rules)
    assert "50W to 550W" in result["reply"]
    mock_llm.assert_not_called()


@patch("app.agent.orchestrator.chat_complete")
async def test_fast_path_miss_calls_llm_unchanged(mock_llm, db_with_rules):
    mock_llm.return_value = await _make_llm_text_response("We'd recommend a 5kWh system.")
    result = await run("What system would you recommend for my restaurant?", "session-fp-2", db_with_rules)
    assert result["reply"] == "We'd recommend a 5kWh system."
    mock_llm.assert_called_once()


@patch("app.agent.orchestrator.chat_complete_stream")
async def test_stream_fast_path_hit_skips_llm(mock_stream, db_with_rules):
    chunks = [c async for c in run_stream("What warranty do your batteries come with?", "session-fp-3", db_with_rules)]
    assert "2-year warranty" in "".join(chunks)
    mock_stream.assert_not_called()
```

- [ ] **Step 8: Run the full suite**

Run: `pytest -v`
Expected: PASS, all prior tests plus the 3 new ones.

- [ ] **Step 9: Commit**

```bash
cd /Users/lucasfeng/rest-solar-agent
git add app/agent/fast_path.py app/agent/orchestrator.py tests/test_fast_path.py tests/test_orchestrator.py
git commit -m "Add FAQ/contact-info fast path, wired into run() and run_stream()"
```

---

### Task 3: Product spec fast path

**Files:**
- Modify: `app/agent/fast_path.py`
- Test: `tests/test_fast_path.py`

**Interfaces:**
- Consumes: `score_products`, `format_specs`, `top_confident_match` from `app/agent/catalog_match.py` (Task 1). `Product` from `app.db.models`, queried via `db.execute(select(Product))` the same way `_retrieve_catalog_context` does.
- Produces: extends `try_fast_path`'s coverage; no interface change to its signature.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fast_path.py (append)
from app.db.models import Product


@pytest.mark.asyncio
async def test_product_spec_confident_match(db):
    db.add(Product(name="RTM210M 210W", sku="SP-100-TEST", category="solar_panels", model="RTM210M", wattage="210W", voltage="24V"))
    await db.commit()
    reply = await try_fast_path("What are the specs on the RTM210M?", "en", db)
    assert reply is not None
    assert "210W" in reply
    assert "24V" not in reply or "voltage 24V" in reply  # format_specs renders "voltage 24V"


@pytest.mark.asyncio
async def test_product_spec_no_spec_data_falls_through(db):
    db.add(Product(name="Bare Product", sku="SP-101-TEST", category="solar_panels", model="BareProduct"))
    await db.commit()
    reply = await try_fast_path("What are the specs on the BareProduct?", "en", db)
    assert reply is None


@pytest.mark.asyncio
async def test_product_spec_ambiguous_match_falls_through(db):
    db.add(Product(name="A", sku="SP-102-TEST", category="solar_panels", model="RTM210M", wattage="210W"))
    db.add(Product(name="B", sku="SP-103-TEST", category="solar_panels", model="RTM220M", wattage="220W"))
    await db.commit()
    reply = await try_fast_path("What are the specs on your solar panels?", "en", db)
    assert reply is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_fast_path.py -v -k product_spec`
Expected: all 3 FAIL (no spec-intent handling yet — hits fall through as None already for `test_product_spec_no_spec_data_falls_through`/`test_product_spec_ambiguous_match_falls_through`, which pass vacuously; `test_product_spec_confident_match` FAILs since no reply is generated).

- [ ] **Step 3: Add the spec-intent classifier and product lookup to `fast_path.py`**

Add imports:
```python
from sqlalchemy import select
from app.db.models import Product
from app.agent.catalog_match import score_products, format_specs, top_confident_match
```

Add the spec-intent pattern near `_FAQ_TRIGGERS`:
```python
_SPEC_INTENT_RE = re.compile(
    r"\b(watt|wattage|voltage|capacity|dimensions?|specs?|specification)\b|"
    r"how many watts|what size is|"
    r"\b(puissance|watts?|tension|capacit[ée]|dimensions?|caract[ée]ristiques)\b",
    re.I,
)
_PRICE_INTENT_RE = re.compile(
    r"\b(price|cost|pricing)\b|how much (does|is|for)|"
    r"\b(prix|co[uû]te|tarif)\b|combien\s+(ça\s+)?co[uû]te",
    re.I,
)
```

Add the lookup helper:
```python
async def _spec_reply(message: str, reply_lang: str, db: AsyncSession) -> str | None:
    if not _SPEC_INTENT_RE.search(message) or _PRICE_INTENT_RE.search(message):
        return None  # not a spec question, or mixed spec+price intent — ambiguous
    result = await db.execute(select(Product))
    products = result.scalars().all()
    scored = score_products(message, products)
    product = top_confident_match(scored)
    if product is None:
        return None
    specs = format_specs(product)
    if not specs:
        return None
    if reply_lang == "fr":
        return f"Caractéristiques du {product.model} (SKU {product.sku}) : {specs}."
    return f"The {product.model} ({product.category}, SKU {product.sku}) specs: {specs}."
```

Update `try_fast_path` to try the spec reply when no FAQ topic matched:
```python
async def try_fast_path(message: str, lang: str, db: AsyncSession) -> str | None:
    reply_lang = "fr" if lang == "fr" else "en"

    topic = _classify_faq(message)
    if topic:
        return _FAQ_REPLIES[topic][reply_lang]

    spec_reply = await _spec_reply(message, reply_lang, db)
    if spec_reply is not None:
        return spec_reply

    return None
```

- [ ] **Step 4: Run to verify all pass**

Run: `pytest tests/test_fast_path.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/lucasfeng/rest-solar-agent
git add app/agent/fast_path.py tests/test_fast_path.py
git commit -m "Add product spec fast path"
```

---

### Task 4: Product price fast path

**Files:**
- Modify: `app/agent/fast_path.py`
- Test: `tests/test_fast_path.py`

**Interfaces:**
- Consumes: same helpers as Task 3, plus `Product.price_xaf`.
- Produces: completes `try_fast_path`'s coverage per the design spec.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_fast_path.py (append)
@pytest.mark.asyncio
async def test_product_price_confident_match(db):
    db.add(Product(name="RTM210M 210W", sku="SP-200-TEST", category="solar_panels", model="RTM210M", wattage="210W", price_xaf=18000.0))
    await db.commit()
    reply = await try_fast_path("How much does the RTM210M cost?", "en", db)
    assert reply is not None
    assert "18,000 FCFA" in reply


@pytest.mark.asyncio
async def test_product_price_unset_falls_through(db):
    db.add(Product(name="Unpriced Panel", sku="SP-201-TEST", category="solar_panels", model="UnpricedPanel", wattage="999W"))
    await db.commit()
    reply = await try_fast_path("How much does the UnpricedPanel cost?", "en", db)
    assert reply is None


@pytest.mark.asyncio
async def test_product_price_and_spec_mixed_intent_falls_through(db):
    db.add(Product(name="RTM210M 210W", sku="SP-202-TEST", category="solar_panels", model="RTM210M", wattage="210W", price_xaf=18000.0))
    await db.commit()
    reply = await try_fast_path("What's the price and wattage of the RTM210M?", "en", db)
    assert reply is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_fast_path.py -v -k product_price`
Expected: `test_product_price_confident_match` FAILs (no price handling yet); the other two pass vacuously (already `None` by default).

- [ ] **Step 3: Add the price reply and wire it into `try_fast_path`**

Add to `fast_path.py`:
```python
async def _price_reply(message: str, reply_lang: str, db: AsyncSession) -> str | None:
    if not _PRICE_INTENT_RE.search(message) or _SPEC_INTENT_RE.search(message):
        return None  # not a price question, or mixed price+spec intent — ambiguous
    result = await db.execute(select(Product))
    products = result.scalars().all()
    scored = score_products(message, products)
    product = top_confident_match(scored)
    if product is None or not product.price_xaf:
        return None  # no confident match, or unpriced — fall through to the LLM's "Price on request"
    if reply_lang == "fr":
        return f"Le {product.model} coûte {product.price_xaf:,.0f} FCFA l'unité (prix de détail à Douala, unité seule)."
    return f"The {product.model} costs {product.price_xaf:,.0f} FCFA each (Douala, single-unit retail price)."
```

Update `try_fast_path`:
```python
async def try_fast_path(message: str, lang: str, db: AsyncSession) -> str | None:
    reply_lang = "fr" if lang == "fr" else "en"

    topic = _classify_faq(message)
    if topic:
        return _FAQ_REPLIES[topic][reply_lang]

    price_reply = await _price_reply(message, reply_lang, db)
    if price_reply is not None:
        return price_reply

    spec_reply = await _spec_reply(message, reply_lang, db)
    if spec_reply is not None:
        return spec_reply

    return None
```

(Price is checked before spec so a message matching only the price pattern doesn't accidentally fall into the spec branch — both branches already refuse mixed intent via their own guard, so order between them only matters for single-intent messages, where it's a no-op either way.)

- [ ] **Step 4: Run to verify all pass**

Run: `pytest tests/test_fast_path.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/lucasfeng/rest-solar-agent
git add app/agent/fast_path.py tests/test_fast_path.py
git commit -m "Add product price fast path"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers the spec's "extracted shared scoring helper" architecture point. Task 2 covers FAQ + contact-info (category 1-2 from the spec) plus the `run()`/`run_stream()` wiring. Tasks 3-4 cover product spec and product price (categories 3-4), including the two live-data boundary cases the spec calls out (no-spec-data product, unpriced product) and the mixed-intent fallback the spec requires.
- **Placeholder scan:** no TBD/TODO; every step has literal code.
- **Type/name consistency:** `try_fast_path(message, lang, db)` signature is identical everywhere it's referenced (spec, Task 2 wiring, Task 3/4 additions). `score_products`, `format_specs`, `top_confident_match` names match between Task 1's definition and Tasks 3-4's usage.
