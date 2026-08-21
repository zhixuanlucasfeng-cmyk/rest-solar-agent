import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()


def send_ticket_email(ticket_id: int, subject: str, body: str) -> dict:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    admin_email = os.getenv("ADMIN_EMAIL", "")

    if not all([smtp_host, smtp_user, smtp_pass, admin_email]):
        return {"status": "skipped", "reason": "SMTP not configured"}

    msg = MIMEText(f"Ticket #{ticket_id}\n\n{body}")
    msg["Subject"] = f"[RestarSolar] {subject}"
    msg["From"] = smtp_user
    msg["To"] = admin_email

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return {"status": "sent", "ticket_id": ticket_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


async def export_conversations_csv(db) -> dict:
    from sqlalchemy import select
    from app.db.models import Conversation, Message

    result = await db.execute(
        select(Conversation, Message)
        .outerjoin(Message, Message.conversation_id == Conversation.id)
        .order_by(Conversation.id, Message.created_at)
    )
    rows = result.all()
    return {"status": "done", "rows": len(rows)}
