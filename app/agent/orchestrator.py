import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.agent.language_detector import detect_language
from app.agent.rule_engine import get_matching_rules
from app.rag.embedder import embed
from app.rag.retriever import query
from app.llm.client import chat_complete
from app.tools import get_tools, get_tool_map
from app.db.models import Conversation, Message

DISTANCE_THRESHOLD = 0.5
HISTORY_LIMIT = 10

_SYSTEM_TEMPLATE = (
    "You are a helpful bilingual customer-service agent for Rest Solar, "
    "a solar energy company supplying products from China to Cameroon.\n\n"
    "Reply language: {reply_language}. Always reply in the same language the customer used.\n\n"
    "Business rules (follow these exactly):\n{rules_text}\n\n"
    "Be honest. If you lack specific information, say so clearly and offer to raise a support ticket."
)


async def run(message: str, session_id: str, db: AsyncSession) -> dict:
    """Run the full agent pipeline. Returns {"reply": str, "language": str}."""

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

    query_vec = embed(message)
    chunks = query(query_vec, n_results=3)
    relevant = [c for c in chunks if c["distance"] < DISTANCE_THRESHOLD]

    context_block = ""
    if relevant:
        context_block = "Relevant information from our knowledge base:\n" + "\n---\n".join(
            c["text"] for c in relevant
        )

    system_content = _SYSTEM_TEMPLATE.format(
        reply_language="French" if lang == "fr" else "English",
        rules_text=rules_text,
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

    user_content = message
    if context_block:
        user_content = f"{context_block}\n\nCustomer question: {message}"
    messages.append({"role": "user", "content": user_content})

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
