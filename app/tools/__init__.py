from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.base import BaseTool
from app.tools.currency import CurrencyTool
from app.tools.logistics import LogisticsTool
from app.tools.quote import QuoteTool
from app.tools.order import OrderTool, CreateOrderTool
from app.tools.ticket import TicketTool


def get_tools(db: AsyncSession, conversation=None) -> list[BaseTool]:
    return [
        CurrencyTool(),
        LogisticsTool(),
        QuoteTool(db),
        OrderTool(db),
        CreateOrderTool(db, conversation),
        TicketTool(db),
    ]


def get_tool_map(db: AsyncSession, conversation=None) -> dict[str, BaseTool]:
    return {t.name: t for t in get_tools(db, conversation)}
