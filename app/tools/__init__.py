from sqlalchemy.ext.asyncio import AsyncSession
from app.tools.base import BaseTool
from app.tools.currency import CurrencyTool
from app.tools.logistics import LogisticsTool
from app.tools.quote import QuoteTool
from app.tools.order import OrderTool
from app.tools.ticket import TicketTool


def get_tools(db: AsyncSession) -> list[BaseTool]:
    return [
        CurrencyTool(),
        LogisticsTool(),
        QuoteTool(db),
        OrderTool(db),
        TicketTool(db),
    ]


def get_tool_map(db: AsyncSession) -> dict[str, BaseTool]:
    return {t.name: t for t in get_tools(db)}
