import os
import smtplib
from email.mime.text import MIMEText
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "rest_solar",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.task_routes = {"app.worker.*": {"queue": "default"}}


@celery_app.task(name="app.worker.send_ticket_email")
def send_ticket_email(ticket_id: int, subject: str, body: str) -> dict:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    admin_email = os.getenv("ADMIN_EMAIL", "")

    if not all([smtp_host, smtp_user, smtp_pass, admin_email]):
        return {"status": "skipped", "reason": "SMTP not configured"}

    msg = MIMEText(f"Ticket #{ticket_id}\n\n{body}")
    msg["Subject"] = f"[Rest Solar] {subject}"
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


@celery_app.task(name="app.worker.export_conversations_csv")
def export_conversations_csv() -> dict:
    import csv, io, sqlite3
    db_path = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/rest_solar.db")
    db_path = db_path.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.session_id, c.language, c.created_at,
               m.role, m.content, m.created_at
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        ORDER BY c.id, m.created_at
    """)
    rows = cursor.fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["conv_id", "session_id", "language", "conv_created", "role", "content", "msg_created"])
    writer.writerows(rows)

    admin_email = os.getenv("ADMIN_EMAIL", "")
    if admin_email:
        send_ticket_email.apply(args=[0, "Conversation Export Ready", buf.getvalue()])

    return {"status": "done", "rows": len(rows)}
