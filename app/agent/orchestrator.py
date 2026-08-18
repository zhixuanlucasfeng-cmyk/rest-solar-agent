import json
import re
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agent.language_detector import detect_language
from app.agent.rule_engine import get_matching_rules
from app.llm.client import chat_complete, chat_complete_stream, PendingToolCall
from app.tools import get_tools, get_tool_map
from app.db.models import Conversation, Message, Product

HISTORY_LIMIT = 10
CATALOG_N_RESULTS = 5

_LLM_DOWN_REPLY = {
    "en": (
        "Sorry, I'm having trouble connecting right now. Please try again in a "
        "moment, or reach us directly on WhatsApp: Luc Su +237 681 105 611 "
        "(Cameroon) or Tom Yang +86 187 0773 7002 (China)."
    ),
    "fr": (
        "Désolé, je rencontre un problème de connexion en ce moment. "
        "Réessayez dans un instant, ou contactez-nous directement sur "
        "WhatsApp : Luc Su +237 681 105 611 (Cameroun) ou Tom Yang "
        "+86 187 0773 7002 (Chine)."
    ),
}

# Deliberately NOT using embeddings/vector search here: torch+sentence-transformers
# were removed from requirements.txt (see commit 8c88b34) because loading a local
# PyTorch model added 300-400MB RAM and OOM-crashed the Render free tier on every
# chat request. This does plain keyword matching against the `products` table
# instead — zero extra dependencies, works within the 512MB free-tier limit.
_USE_CASE_KEYWORDS = {
    "home_backup": ["home", "house", "backup", "outage", "blackout", "maison", "coupure", "résidentiel", "secours"],
    "shop_fridge": ["fridge", "freezer", "refrigerat", "shop", "cold", "congélateur", "réfrigérat", "boutique", "froid"],
    "borehole_pump": ["pump", "borehole", "well", "water", "forage", "pompe", "puits", "eau"],
    "street_lighting": ["street light", "streetlight", "flood light", "lighting", "lampadaire", "éclairage", "lumière"],
    "business_ess": ["business", "commercial", "factory", "hotel", "entreprise", "usine", "hôtel", "ess", "smartcube"],
}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


_ABOVE_WORDS = r"above|over|more than|greater than|at least|plus de|au moins|au-dessus de"
_BELOW_WORDS = r"below|under|less than|fewer than|moins de|en dessous de"
_WATT_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*w", re.I)
_WATT_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*w\b", re.I)


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


async def _retrieve_catalog_context(message: str, db: AsyncSession) -> str:
    """Keyword-match the user's message against the products table and
    return a compact text block for the top-scoring products, or "" if
    nothing scores above zero."""
    result = await db.execute(select(Product))
    products = result.scalars().all()
    if not products:
        return ""

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
        # exact model/sku mention is a strong signal
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

        if p.featured and score > 0:
            score += 1  # nudge featured/recommended models up among otherwise-tied matches

        if score > 0:
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:CATALOG_N_RESULTS]
    if not top:
        return ""

    lines = []
    for _, p in top:
        specs = ", ".join(filter(None, [
            p.wattage, p.power_kw, p.capacity_ah, p.capacity_kwh,
            f"voltage {p.voltage}" if p.voltage else None,
            f"dimensions {p.dimensions}" if p.dimensions else None,
        ]))
        feats = f" Features: {p.features}." if p.features else ""
        price_bit = (
            f"{p.price_xaf:,.0f} FCFA each (Douala, single-unit retail price)."
            if p.price_xaf
            else "Price on request — datasheet available."
        )
        featured_bit = " (★ Featured/recommended model)" if p.featured else ""
        lines.append(
            f"- {p.model} ({p.category}{'/' + p.subcategory if p.subcategory else ''}, SKU {p.sku}){featured_bit}: "
            f"{specs}.{feats} {price_bit}"
        )
    return (
        "2026 catalog matches for this question (mention naturally when a match is marked "
        "★ Featured/recommended — e.g. call it one of our top picks):\n" + "\n".join(lines)
    )

_FAQ_CONTENT = """
Q: What solar panel sizes do you sell?
A: We stock monocrystalline solar panels ranging from 50W to 550W. Our most popular sizes for homes are the 200W and 330W panels, while the 450W and 550W panels are preferred for businesses and borehole pumping systems.

Q: What warranty do your batteries come with?
A: Our lithium LiFePO4 batteries carry a 2-year warranty against manufacturing defects. Tubular gel batteries carry a 1-year warranty. All warranty claims must be accompanied by proof of purchase and installation documentation.

Q: Do you deliver to cities outside Douala?
A: Yes, we deliver across Cameroon including Yaoundé, Bafoussam, Bamenda, Garoua, Maroua, Bertoua, and all major cities. Delivery times and costs vary by location. Contact us for a quote specific to your area.

Q: How long does a shipment from China take?
A: Sea freight from our factory in China to Douala port typically takes 30 to 45 days, depending on vessel schedules and port clearance. We also offer faster air freight for urgent orders, which takes 7 to 10 days at higher cost.

Q: What is the Cameroon import duty on solar panels?
A: As of our most recent information, solar panels are classified under HS code 8541.40 and attract a 10% import duty plus 19.25% VAT on the CIF value. These rates can change — always verify with a licensed customs broker before importing.

Q: Quelles tailles de panneaux solaires vendez-vous ?
R: Nous proposons des panneaux solaires monocristallins de 50W à 550W. Les tailles les plus populaires pour les foyers sont les panneaux 200W et 330W, tandis que les panneaux 450W et 550W sont privilégiés pour les entreprises et les systèmes de pompage de forage.

Q: Quelle garantie offrez-vous sur les batteries ?
R: Nos batteries lithium LiFePO4 bénéficient d'une garantie de 2 ans contre les défauts de fabrication. Les batteries tubulaires gel bénéficient d'une garantie d'un an. Toute demande de garantie doit être accompagnée d'un justificatif d'achat et d'une documentation d'installation.

Q: Livrez-vous en dehors de Douala ?
R: Oui, nous livrons partout au Cameroun, notamment à Yaoundé, Bafoussam, Bamenda, Garoua, Maroua, Bertoua et dans toutes les grandes villes. Les délais et frais de livraison varient selon la localisation. Contactez-nous pour un devis adapté à votre zone.

Q: Combien de temps prend une expédition depuis la Chine ?
R: Le fret maritime depuis notre usine en Chine jusqu'au port de Douala prend généralement 30 à 45 jours, selon les plannings des navires et le dédouanement. Nous proposons également le fret aérien pour les commandes urgentes, avec un délai de 7 à 10 jours, à un coût plus élevé.

Q: Quels sont les droits d'importation au Cameroun pour les panneaux solaires ?
R: Selon nos dernières informations, les panneaux solaires sont classés sous le code SH 8541.40 et sont soumis à 10 % de droits d'importation plus 19,25 % de TVA sur la valeur CAF. Ces taux peuvent évoluer — vérifiez toujours auprès d'un transitaire agréé avant toute importation.
""".strip()

_CONTACT_INFO = """
SHOP LOCATION & SALES CONTACTS (share these whenever you cannot fully answer, or at the end of any conversation where the customer needs further help):

- Showroom address: Rue Léman, Douala, Cameroon
- Luc Su (Cameroon sales): WhatsApp +237 681 105 611
- Tom Yang (China sales): WhatsApp +86 187 0773 7002

When you cannot answer a question, say so honestly and then share BOTH sales contacts (Luc Su and Tom Yang) plus the showroom address so the customer can get help directly. Do the same when closing a conversation if the customer still has unresolved needs.

Always write the names "Luc Su" and "Tom Yang" exactly as spelled here, in Latin letters — never transliterate or translate them into Chinese characters or any other script, regardless of the reply language.
""".strip()

_SYSTEM_TEMPLATE = (
    "You are a helpful bilingual customer-service agent for Restar Solar, "
    "a solar energy company supplying products from China to Cameroon.\n\n"
    "Reply language: {reply_language}. Always reply in the same language the customer used.\n\n"
    "Communication style (STRICTLY follow these):\n"
    "- Keep replies SHORT and DIRECT — 2 to 4 sentences max.\n"
    "- NEVER use tables, markdown headers, or bullet lists.\n"
    "- Write plain conversational sentences only.\n"
    "- For prices, just say them naturally: e.g. '200W mono panel costs 22,500 FCFA each (under 20 units).'\n\n"
    "Business rules (follow these exactly):\n{rules_text}\n\n"
    "Product knowledge base:\n{faq_content}\n\n"
    "{contact_info}\n\n"
    "Be honest. If you lack specific information, share the shop contacts above and offer to raise a support ticket."
)


async def run(message: str, session_id: str, db: AsyncSession) -> dict:
    """Run the full agent pipeline. Returns {\"reply\": str, \"language\": str}."""

    lang = detect_language(message)

    result = await db.execute(
        select(Conversation).where(Conversation.session_id == session_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(session_id=session_id, language=lang)
        db.add(conv)
        await db.flush()

    rule_bodies = await get_matching_rules(message, db)
    rules_text = "\n".join(f"- {body}" for body in rule_bodies) if rule_bodies else "None."

    catalog_context = await _retrieve_catalog_context(message, db)
    faq_content = f"{_FAQ_CONTENT}\n\n{catalog_context}" if catalog_context else _FAQ_CONTENT

    system_content = _SYSTEM_TEMPLATE.format(
        reply_language="French" if lang == "fr" else "English",
        rules_text=rules_text,
        faq_content=faq_content,
        contact_info=_CONTACT_INFO,
    )

    hist_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    history = list(reversed(hist_result.scalars().all()))

    messages: list[dict] = [{"role": "system", "content": system_content}]
    for m in history:
        role = m.role if m.role in ("user", "assistant") else "assistant"
        messages.append({"role": role, "content": m.content})
    messages.append({"role": "user", "content": message})

    tools_list = get_tools(db)
    tool_defs = [t.definition() for t in tools_list]
    tool_map = get_tool_map(db)

    final_reply: str
    try:
        llm_msg = await chat_complete(messages, tools=tool_defs)

        if llm_msg.tool_calls:
            tc = llm_msg.tool_calls[0]
            tool_name = tc.function.name
            tool_params = json.loads(tc.function.arguments)

            tool = tool_map.get(tool_name)
            if tool:
                tool_result = await tool.call(tool_params)

                tool_call_entry = {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tc.function.arguments},
                }
                extra_content = getattr(tc, "extra_content", None)
                if extra_content:
                    tool_call_entry["extra_content"] = extra_content

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call_entry],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result),
                })
                final_msg = await chat_complete(messages)
                final_reply = final_msg.content or ""

                db.add(Message(
                    conversation_id=conv.id,
                    role="tool",
                    content=json.dumps(tool_result),
                    tool_name=tool_name,
                ))
            else:
                final_reply = f"[Tool '{tool_name}' not available]"
        else:
            final_reply = llm_msg.content or ""
    except Exception:
        # Broad on purpose: this wraps the LLM call *and* tool execution.
        # A bug in any one tool implementation (see app/tools/quote.py's
        # missing-price crash, the actual cause of the live intermittent-500
        # incident this except clause was widened to fix) must not 500 the
        # whole /api/chat request — degrade to the same friendly message the
        # LLM-unavailable case already used.
        final_reply = _LLM_DOWN_REPLY["fr"] if lang == "fr" else _LLM_DOWN_REPLY["en"]

    db.add(Message(conversation_id=conv.id, role="user", content=message))
    db.add(Message(conversation_id=conv.id, role="assistant", content=final_reply))
    await db.commit()

    return {"reply": final_reply, "language": lang}


async def run_stream(
    message: str, session_id: str, db: AsyncSession
) -> AsyncGenerator[str, None]:
    """Streaming variant of run(). Yields reply tokens one at a time."""
    lang = detect_language(message)

    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
    conv = result.scalar_one_or_none()
    if not conv:
        conv = Conversation(session_id=session_id, language=lang)
        db.add(conv)
        await db.flush()

    rule_bodies = await get_matching_rules(message, db)
    rules_text = "\n".join(f"- {body}" for body in rule_bodies) if rule_bodies else "None."

    catalog_context = await _retrieve_catalog_context(message, db)
    faq_content = f"{_FAQ_CONTENT}\n\n{catalog_context}" if catalog_context else _FAQ_CONTENT

    system_content = _SYSTEM_TEMPLATE.format(
        reply_language="French" if lang == "fr" else "English",
        rules_text=rules_text,
        faq_content=faq_content,
        contact_info=_CONTACT_INFO,
    )

    hist_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    history = list(reversed(hist_result.scalars().all()))

    messages: list[dict] = [{"role": "system", "content": system_content}]
    for m in history:
        role = m.role if m.role in ("user", "assistant") else "assistant"
        messages.append({"role": role, "content": m.content})
    messages.append({"role": "user", "content": message})

    tools_list = get_tools(db)
    tool_defs = [t.definition() for t in tools_list]
    tool_map = get_tool_map(db)

    db.add(Message(conversation_id=conv.id, role="user", content=message))

    # Stream directly instead of doing a separate blocking "does this need a
    # tool?" call first — that was a full extra LLM round trip on every
    # message, even ones that never call a tool. chat_complete_stream()
    # streams text tokens as they arrive and only surfaces tool call(s) (as
    # a list[PendingToolCall]) once the stream ends, so the common
    # no-tool-call case gets its first token immediately.
    collected_reply: list[str] = []
    pending_calls: list[PendingToolCall] = []
    try:
        async for item in chat_complete_stream(messages, tools=tool_defs):
            if isinstance(item, list):
                pending_calls = item
            else:
                collected_reply.append(item)
                yield item
    except Exception:
        if not collected_reply:
            fallback = _LLM_DOWN_REPLY["fr"] if lang == "fr" else _LLM_DOWN_REPLY["en"]
            collected_reply.append(fallback)
            yield fallback
        full_reply = "".join(collected_reply)
        db.add(Message(conversation_id=conv.id, role="assistant", content=full_reply))
        await db.commit()
        return

    if pending_calls:
        tc = pending_calls[0]
        tool_name = tc.name
        tool_params = json.loads(tc.arguments) if tc.arguments else {}
        tool = tool_map.get(tool_name)
        tool_result: dict = {}
        if tool:
            try:
                tool_result = await tool.call(tool_params)
            except Exception:
                # Same rationale as the run() fix: a tool bug (e.g.
                # app/tools/quote.py's missing-price crash) must not blow up
                # the stream — degrade to the friendly fallback instead.
                fallback = _LLM_DOWN_REPLY["fr"] if lang == "fr" else _LLM_DOWN_REPLY["en"]
                collected_reply.append(fallback)
                yield fallback
                full_reply = "".join(collected_reply)
                db.add(Message(conversation_id=conv.id, role="assistant", content=full_reply))
                await db.commit()
                return
        tool_call_entry = {
            "id": tc.id,
            "type": "function",
            "function": {"name": tool_name, "arguments": tc.arguments},
        }
        if tc.extra_content:
            tool_call_entry["extra_content"] = tc.extra_content
        final_messages = messages + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call_entry],
            },
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            },
        ]
        db.add(Message(conversation_id=conv.id, role="tool", content=json.dumps(tool_result), tool_name=tool_name))

        try:
            async for token in chat_complete_stream(final_messages):
                if isinstance(token, str):
                    collected_reply.append(token)
                    yield token
        except Exception:
            if not collected_reply:
                fallback = _LLM_DOWN_REPLY["fr"] if lang == "fr" else _LLM_DOWN_REPLY["en"]
                collected_reply.append(fallback)
                yield fallback

    full_reply = "".join(collected_reply)
    db.add(Message(conversation_id=conv.id, role="assistant", content=full_reply))
    await db.commit()
