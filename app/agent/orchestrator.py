import json
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agent.language_detector import detect_language
from app.agent.rule_engine import get_matching_rules
from app.llm.client import chat_complete, chat_complete_stream
from app.tools import get_tools, get_tool_map
from app.db.models import Conversation, Message

HISTORY_LIMIT = 10

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

    system_content = _SYSTEM_TEMPLATE.format(
        reply_language="French" if lang == "fr" else "English",
        rules_text=rules_text,
        faq_content=_FAQ_CONTENT,
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
    llm_msg = await chat_complete(messages, tools=tool_defs)

    final_reply: str
    if llm_msg.tool_calls:
        tc = llm_msg.tool_calls[0]
        tool_name = tc.function.name
        tool_params = json.loads(tc.function.arguments)

        tool = tool_map.get(tool_name)
        if tool:
            tool_result = await tool.call(tool_params)

            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tc.function.arguments},
                }],
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

    system_content = _SYSTEM_TEMPLATE.format(
        reply_language="French" if lang == "fr" else "English",
        rules_text=rules_text,
        faq_content=_FAQ_CONTENT,
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

    probe_msg = await chat_complete(messages, tools=tool_defs)

    final_messages = messages
    if probe_msg.tool_calls:
        tc = probe_msg.tool_calls[0]
        tool_name = tc.function.name
        tool_params = json.loads(tc.function.arguments)
        tool = tool_map.get(tool_name)
        tool_result: dict = {}
        if tool:
            tool_result = await tool.call(tool_params)
        final_messages = messages + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tc.function.arguments},
                }],
            },
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(tool_result),
            },
        ]
        db.add(Message(conversation_id=conv.id, role="tool", content=json.dumps(tool_result), tool_name=tool_name))

    db.add(Message(conversation_id=conv.id, role="user", content=message))

    collected_reply = []
    async for token in chat_complete_stream(final_messages):
        collected_reply.append(token)
        yield token

    full_reply = "".join(collected_reply)
    db.add(Message(conversation_id=conv.id, role="assistant", content=full_reply))
    await db.commit()
