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
