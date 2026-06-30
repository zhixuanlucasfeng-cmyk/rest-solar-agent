from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.base import BaseTool
from app.db.models import Ticket
from app.worker import send_ticket_email


class TicketTool(BaseTool):
    name = "create_ticket"
    description = (
        "Create a support ticket and notify the Rest Solar team by email. "
        "Use when the customer has an issue that needs human follow-up."
    )

    def __init__(self, db: AsyncSession):
        self._db = db

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "subject": {
                            "type": "string",
                            "description": "Short summary of the issue",
                        },
                        "body": {
                            "type": "string",
                            "description": "Full description of the issue",
                        },
                        "conversation_id": {
                            "type": "integer",
                            "description": "Optional conversation ID to link this ticket",
                        },
                    },
                    "required": ["subject", "body"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        subject = str(params["subject"])
        body = str(params["body"])
        conversation_id = params.get("conversation_id")

        ticket = Ticket(
            conversation_id=conversation_id,
            subject=subject,
            body=body,
            status="open",
        )
        self._db.add(ticket)
        await self._db.flush()
        await self._db.refresh(ticket)

        send_ticket_email(ticket.id, subject, body)

        return {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "confirmation": f"Support ticket #{ticket.id} created. Our team will contact you shortly.",
        }
