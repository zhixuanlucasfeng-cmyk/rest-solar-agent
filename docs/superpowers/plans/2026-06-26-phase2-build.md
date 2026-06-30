# Rest Solar Agent — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote Phase 1 demo to production-ready: Docker Compose packaging, 4 new AI tools (Quote/Logistics/Order/Ticket), WebSocket streaming chat with human takeover, JWT-gated admin backend, and mobile-first PWA UI.

**Architecture:** Four Docker services (nginx → FastAPI app, Celery worker, Redis); new tools extend the existing `BaseTool` ABC; WebSocket endpoint replaces HTTP POST for realtime token streaming; admin UI uses Jinja2+HTMX behind JWT httpOnly-cookie auth.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy+aiosqlite, ChromaDB, Celery+Redis, python-jose, passlib[bcrypt], HTMX, Docker Compose, nginx.

## Global Constraints

- Python 3.12 — no version change
- SQLite + `create_all()` only — no Alembic
- No hardcoded secrets — all via `.env` / Docker environment
- Celery broker: Redis only (no RabbitMQ)
- Admin frontend: Jinja2 + HTMX — no React/Vue/Next.js
- nginx: gzip on, WebSocket `Upgrade` headers set
- All new tools implement `BaseTool` ABC from `app/tools/base.py` without modifying it
- Branch: `phase-2-build`

---

## File Map

**New files:**
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `nginx/nginx.conf`
- `app/worker.py` — Celery app + tasks
- `.env.example` — updated
- `app/tools/quote.py` — QuoteTool
- `app/tools/logistics.py` — LogisticsTool
- `app/tools/order.py` — OrderTool
- `app/tools/ticket.py` — TicketTool
- `app/api/ws_manager.py` — ConnectionManager (in-memory WebSocket registry)
- `app/api/ws.py` — `/ws/{conversation_id}` + `/ws/admin/{user_id}` endpoints
- `app/admin/__init__.py`
- `app/admin/auth.py` — password hashing, JWT create/verify
- `app/admin/deps.py` — `get_current_admin` FastAPI dependency
- `app/admin/routes.py` — all admin HTTP + page routes
- `templates/admin/base.html`
- `templates/admin/login.html`
- `templates/admin/dashboard.html`
- `templates/admin/conversations.html`
- `templates/admin/conversation_detail.html`
- `templates/admin/rules.html`
- `templates/admin/products.html`
- `templates/admin/orders.html`
- `templates/admin/tickets.html`
- `templates/admin/users.html`
- `templates/admin/reports.html`
- `templates/mobile.html`
- `static/manifest.json`
- `static/sw.js`
- `tests/test_quote_tool.py`
- `tests/test_logistics_tool.py`
- `tests/test_order_tool.py`
- `tests/test_ticket_tool.py`
- `tests/test_websocket.py`
- `tests/test_admin_auth.py`
- `tests/test_admin_routes.py`

**Modified files:**
- `requirements.txt` — add celery[redis], redis, python-jose[cryptography], passlib[bcrypt], httpx already present
- `app/db/models.py` — add Product, Order, Ticket, AdminUser models
- `app/tools/__init__.py` — becomes central tool registry (TOOLS list + TOOL_MAP)
- `app/agent/orchestrator.py` — import from `app.tools` registry; add `run_stream()`
- `app/llm/client.py` — add `chat_complete_stream()` async generator
- `app/main.py` — include ws router, admin router, `/mobile` route

---

## Task 1: Docker Infrastructure

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `docker-compose.prod.yml`
- Create: `nginx/nginx.conf`
- Create: `app/worker.py`
- Create: `.env.example`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: running 4-service stack; `celery_app` importable from `app.worker`; `send_ticket_email(ticket_id, subject, body)` Celery task

- [ ] **Step 1: Update requirements.txt**

Replace the existing `requirements.txt` with:

```
agent-squad[openai]>=1.0.2
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-dotenv>=1.0.0
openai>=1.30.0
chromadb>=0.5.0
sentence-transformers>=2.2.0,<3.0
numpy<2.0
scipy<1.14
langdetect>=1.0.9
sqlalchemy[asyncio]>=2.0.0
aiosqlite>=0.20.0
httpx>=0.27.0
pypdf>=3.0.0
openpyxl>=3.1.0
jinja2>=3.1.0
python-multipart>=0.0.9
beautifulsoup4>=4.12.0
celery[redis]>=5.3.0
redis>=5.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

- [ ] **Step 2: Write Dockerfile**

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data chroma_db

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Write docker-compose.yml**

```yaml
services:
  nginx:
    image: nginx:1.27-alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - app
    restart: unless-stopped

  app:
    build: .
    env_file: .env
    volumes:
      - ./data/sqlite:/app/data
      - ./data/chroma:/app/chroma_db
      - huggingface_cache:/root/.cache/huggingface
    depends_on:
      - redis
    restart: unless-stopped

  worker:
    build: .
    command: celery -A app.worker worker --loglevel=info -Q default
    env_file: .env
    volumes:
      - ./data/sqlite:/app/data
      - ./data/chroma:/app/chroma_db
      - huggingface_cache:/root/.cache/huggingface
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

volumes:
  huggingface_cache:
```

- [ ] **Step 4: Write docker-compose.prod.yml**

```yaml
services:
  nginx:
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro

  app:
    environment:
      - NODE_ENV=production
```

- [ ] **Step 5: Write nginx/nginx.conf**

```nginx
upstream app {
    server app:8000;
}

server {
    listen 80;
    server_name _;

    gzip on;
    gzip_types text/plain application/json application/javascript text/css text/html;
    gzip_min_length 1024;

    location /static/ {
        proxy_pass http://app;
    }

    location /ws/ {
        proxy_pass http://app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    location / {
        proxy_pass http://app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

- [ ] **Step 6: Write app/worker.py**

```python
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
```

- [ ] **Step 7: Write .env.example**

```
# LLM
LLM_API_KEY=your-openrouter-key
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=google/gemini-2.0-flash-exp

# Database
DATABASE_URL=sqlite+aiosqlite:///./data/rest_solar.db

# Currency (optional — uses static fallback if absent)
CURRENCY_API_KEY=

# Redis / Celery
REDIS_URL=redis://redis:6379/0

# Admin JWT
ADMIN_SECRET_KEY=change-me-to-a-random-64-char-string

# Email (optional — tickets still created; email skipped if absent)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASS=your-app-password
ADMIN_EMAIL=admin@restsolar.com
```

- [ ] **Step 8: Verify docker compose builds**

```bash
docker compose build
```

Expected: all 3 build stages complete with exit 0. The `app` and `worker` images should show `Successfully built`.

- [ ] **Step 9: Commit**

```bash
git add Dockerfile docker-compose.yml docker-compose.prod.yml nginx/ app/worker.py .env.example requirements.txt
git commit -m "feat: Docker infra — nginx + app + worker + redis compose stack"
```

---

## Task 2: New DB Models

**Files:**
- Modify: `app/db/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `Product`, `Order`, `Ticket`, `AdminUser` SQLAlchemy mapped classes importable from `app.db.models`

- [ ] **Step 1: Write failing test**

Create `tests/test_models.py`:

```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, Product, Order, Ticket, AdminUser


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.mark.asyncio
async def test_product_model(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        p = Product(name="Solar Panel 400W", sku="SP-400", price_cny=1200.0, price_xaf=108000.0, weight_kg=22.0, stock=50)
        s.add(p)
        await s.commit()
        await s.refresh(p)
    assert p.id is not None
    assert p.duty_rate == 0.30
    assert p.vat_rate == 0.1925


@pytest.mark.asyncio
async def test_order_model(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        o = Order(order_number="ORD-001", customer_name="Jean Dupont")
        s.add(o)
        await s.commit()
        await s.refresh(o)
    assert o.id is not None
    assert o.status == "pending"


@pytest.mark.asyncio
async def test_ticket_model(engine):
    from app.db.models import Conversation
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        conv = Conversation(session_id="test-sess", language="fr")
        s.add(conv)
        await s.flush()
        t = Ticket(conversation_id=conv.id, subject="Issue", body="Details here")
        s.add(t)
        await s.commit()
        await s.refresh(t)
    assert t.id is not None
    assert t.status == "open"


@pytest.mark.asyncio
async def test_admin_user_model(engine):
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        u = AdminUser(email="admin@test.com", password_hash="hashed", role="superadmin")
        s.add(u)
        await s.commit()
        await s.refresh(u)
    assert u.id is not None
    assert u.role == "superadmin"
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd /Users/lucasfeng/rest-solar-agent
source .venv/bin/activate
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'Product' from 'app.db.models'`

- [ ] **Step 3: Add new models to app/db/models.py**

Append after the existing `Rule` class:

```python
from sqlalchemy import Float


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    price_cny: Mapped[float] = mapped_column(Float, nullable=False)
    price_xaf: Mapped[float] = mapped_column(Float, nullable=False)
    duty_rate: Mapped[float] = mapped_column(Float, default=0.30)
    vat_rate: Mapped[float] = mapped_column(Float, default=0.1925)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[Text] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

Also add `Float` to the imports at the top of `app/db/models.py`:
```python
from sqlalchemy import Integer, String, Text, Boolean, DateTime, ForeignKey, Float
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_models.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py tests/test_models.py
git commit -m "feat: DB models — Product, Order, Ticket, AdminUser"
```

---

## Task 3: QuoteTool

**Files:**
- Create: `app/tools/quote.py`
- Test: `tests/test_quote_tool.py`

**Interfaces:**
- Consumes: `BaseTool` from `app.tools.base`; `Product` from `app.db.models`; `get_db` from `app.db.session`
- Produces: `QuoteTool` class with `name = "get_quote"`, `async def call(params) -> dict` returning `{"sku", "quantity", "unit_price_cny", "unit_price_xaf", "subtotal_cny", "duty_cny", "vat_cny", "shipping_cny", "total_cny", "total_xaf"}`

- [ ] **Step 1: Write failing test**

Create `tests/test_quote_tool.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, Product
from app.tools.quote import QuoteTool


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(Product(
            name="Solar Panel 400W", sku="SP-400",
            price_cny=1200.0, price_xaf=108000.0,
            duty_rate=0.30, vat_rate=0.1925,
            weight_kg=22.0, stock=10
        ))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_quote_known_sku(db_session):
    tool = QuoteTool(db_session)
    result = await tool.call({"sku": "SP-400", "quantity": 2})
    assert result["sku"] == "SP-400"
    assert result["quantity"] == 2
    assert result["subtotal_cny"] == pytest.approx(2400.0)
    assert result["duty_cny"] == pytest.approx(720.0)       # 2400 * 0.30
    assert result["vat_cny"] == pytest.approx(462.0)        # 2400 * 0.1925
    assert result["shipping_cny"] == pytest.approx(968.0)   # 22kg * 2 * 22 CNY/kg
    assert "total_cny" in result
    assert "total_xaf" in result


@pytest.mark.asyncio
async def test_quote_unknown_sku(db_session):
    tool = QuoteTool(db_session)
    result = await tool.call({"sku": "UNKNOWN", "quantity": 1})
    assert "error" in result


def test_definition():
    import asyncio
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as s:
            tool = QuoteTool(s)
            defn = tool.definition()
            assert defn["type"] == "function"
            assert defn["function"]["name"] == "get_quote"
            assert "sku" in defn["function"]["parameters"]["properties"]
            assert "quantity" in defn["function"]["parameters"]["properties"]
    asyncio.run(_run())
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_quote_tool.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tools.quote'`

- [ ] **Step 3: Write app/tools/quote.py**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.tools.base import BaseTool
from app.db.models import Product

SHIPPING_RATE_CNY_PER_KG = 22.0  # sea freight China→Cameroon, per kg


class QuoteTool(BaseTool):
    name = "get_quote"
    description = (
        "Get a price quote for a Rest Solar product. "
        "Returns subtotal, import duty, VAT, shipping, and total in CNY and XAF."
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
                        "sku": {
                            "type": "string",
                            "description": "Product SKU code, e.g. SP-400",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Number of units",
                            "minimum": 1,
                        },
                    },
                    "required": ["sku", "quantity"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        sku = str(params["sku"]).upper()
        qty = int(params["quantity"])

        result = await self._db.execute(select(Product).where(Product.sku == sku))
        product = result.scalar_one_or_none()
        if not product:
            return {"error": f"Product with SKU '{sku}' not found"}

        subtotal_cny = round(product.price_cny * qty, 2)
        duty_cny = round(subtotal_cny * product.duty_rate, 2)
        vat_cny = round(subtotal_cny * product.vat_rate, 2)
        weight_total = (product.weight_kg or 0.0) * qty
        shipping_cny = round(weight_total * SHIPPING_RATE_CNY_PER_KG, 2)
        total_cny = round(subtotal_cny + duty_cny + vat_cny + shipping_cny, 2)
        total_xaf = round(total_cny * (product.price_xaf / product.price_cny), 2)

        return {
            "sku": product.sku,
            "name": product.name,
            "quantity": qty,
            "unit_price_cny": product.price_cny,
            "unit_price_xaf": product.price_xaf,
            "subtotal_cny": subtotal_cny,
            "duty_cny": duty_cny,
            "vat_cny": vat_cny,
            "shipping_cny": shipping_cny,
            "total_cny": total_cny,
            "total_xaf": total_xaf,
        }
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_quote_tool.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/tools/quote.py tests/test_quote_tool.py
git commit -m "feat: QuoteTool — SKU + quantity → subtotal, duty, VAT, shipping, total"
```

---

## Task 4: LogisticsTool

**Files:**
- Create: `app/tools/logistics.py`
- Test: `tests/test_logistics_tool.py`

**Interfaces:**
- Produces: `LogisticsTool` class with `name = "get_logistics"`, `call(params) -> dict` returning `{"origin", "destination", "weight_kg", "mode", "transit_days", "freight_cny", "freight_xaf"}`

- [ ] **Step 1: Write failing test**

Create `tests/test_logistics_tool.py`:

```python
import pytest
from app.tools.logistics import LogisticsTool


@pytest.mark.asyncio
async def test_sea_freight():
    tool = LogisticsTool()
    result = await tool.call({"origin": "Shenzhen", "destination": "Douala", "weight_kg": 100, "mode": "sea"})
    assert result["mode"] == "sea"
    assert result["transit_days"] == 30
    assert result["freight_cny"] == pytest.approx(100 * 8.0)
    assert "freight_xaf" in result


@pytest.mark.asyncio
async def test_air_freight():
    tool = LogisticsTool()
    result = await tool.call({"origin": "Guangzhou", "destination": "Douala", "weight_kg": 10, "mode": "air"})
    assert result["mode"] == "air"
    assert result["transit_days"] == 7
    assert result["freight_cny"] == pytest.approx(10 * 45.0)


@pytest.mark.asyncio
async def test_default_mode_is_sea():
    tool = LogisticsTool()
    result = await tool.call({"origin": "Shanghai", "destination": "Douala", "weight_kg": 50})
    assert result["mode"] == "sea"


def test_definition():
    tool = LogisticsTool()
    defn = tool.definition()
    assert defn["function"]["name"] == "get_logistics"
    props = defn["function"]["parameters"]["properties"]
    assert "origin" in props
    assert "destination" in props
    assert "weight_kg" in props
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_logistics_tool.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tools.logistics'`

- [ ] **Step 3: Write app/tools/logistics.py**

```python
from app.tools.base import BaseTool

# Stubbed rates: sea CNY/kg, air CNY/kg, transit days
# Interface is ready for a real freight API integration later.
SEA_RATE_CNY_PER_KG = 8.0
AIR_RATE_CNY_PER_KG = 45.0
SEA_TRANSIT_DAYS = 30
AIR_TRANSIT_DAYS = 7
CNY_TO_XAF = 90.0  # static fallback


class LogisticsTool(BaseTool):
    name = "get_logistics"
    description = (
        "Get estimated shipping time and freight cost from China to Cameroon (Douala port). "
        "Supports sea freight (~30 days) and air freight (~7 days)."
    )

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "description": "Origin city in China, e.g. Shenzhen",
                        },
                        "destination": {
                            "type": "string",
                            "description": "Destination city in Cameroon, e.g. Douala",
                        },
                        "weight_kg": {
                            "type": "number",
                            "description": "Total shipment weight in kilograms",
                        },
                        "mode": {
                            "type": "string",
                            "enum": ["sea", "air"],
                            "description": "Shipping mode: sea (cheaper, slower) or air (faster, expensive). Defaults to sea.",
                        },
                    },
                    "required": ["origin", "destination", "weight_kg"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        origin = str(params["origin"])
        destination = str(params["destination"])
        weight_kg = float(params["weight_kg"])
        mode = str(params.get("mode", "sea")).lower()
        if mode not in ("sea", "air"):
            mode = "sea"

        if mode == "sea":
            transit_days = SEA_TRANSIT_DAYS
            freight_cny = round(weight_kg * SEA_RATE_CNY_PER_KG, 2)
        else:
            transit_days = AIR_TRANSIT_DAYS
            freight_cny = round(weight_kg * AIR_RATE_CNY_PER_KG, 2)

        return {
            "origin": origin,
            "destination": destination,
            "weight_kg": weight_kg,
            "mode": mode,
            "transit_days": transit_days,
            "freight_cny": freight_cny,
            "freight_xaf": round(freight_cny * CNY_TO_XAF, 2),
        }
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_logistics_tool.py -v
```

Expected: 4 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/tools/logistics.py tests/test_logistics_tool.py
git commit -m "feat: LogisticsTool — China→Cameroon sea/air freight (stubbed rates)"
```

---

## Task 5: OrderTool

**Files:**
- Create: `app/tools/order.py`
- Test: `tests/test_order_tool.py`

**Interfaces:**
- Produces: `OrderTool(db)` with `name = "get_order_status"`, `call({"order_number": str}) -> dict`

- [ ] **Step 1: Write failing test**

Create `tests/test_order_tool.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, Order
from app.tools.order import OrderTool


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        session.add(Order(order_number="ORD-2024-001", customer_name="Marie Nguema", status="shipped"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_order_found(db_session):
    tool = OrderTool(db_session)
    result = await tool.call({"order_number": "ORD-2024-001"})
    assert result["order_number"] == "ORD-2024-001"
    assert result["status"] == "shipped"
    assert result["customer_name"] == "Marie Nguema"
    assert "created_at" in result


@pytest.mark.asyncio
async def test_order_not_found(db_session):
    tool = OrderTool(db_session)
    result = await tool.call({"order_number": "NONEXISTENT"})
    assert "error" in result


def test_definition():
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as s:
            tool = OrderTool(s)
            defn = tool.definition()
            assert defn["function"]["name"] == "get_order_status"
    asyncio.run(_run())
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_order_tool.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tools.order'`

- [ ] **Step 3: Write app/tools/order.py**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.tools.base import BaseTool
from app.db.models import Order


class OrderTool(BaseTool):
    name = "get_order_status"
    description = "Look up the status of a customer order by order number."

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
                        "order_number": {
                            "type": "string",
                            "description": "The order number, e.g. ORD-2024-001",
                        },
                    },
                    "required": ["order_number"],
                },
            },
        }

    async def call(self, params: dict) -> dict:
        order_number = str(params["order_number"]).strip()
        result = await self._db.execute(select(Order).where(Order.order_number == order_number))
        order = result.scalar_one_or_none()
        if not order:
            return {"error": f"Order '{order_number}' not found"}
        return {
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "status": order.status,
            "created_at": order.created_at.isoformat(),
        }
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_order_tool.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/tools/order.py tests/test_order_tool.py
git commit -m "feat: OrderTool — order number → status lookup"
```

---

## Task 6: TicketTool + Celery email

**Files:**
- Create: `app/tools/ticket.py`
- Test: `tests/test_ticket_tool.py`

**Interfaces:**
- Consumes: `Ticket` from `app.db.models`; `send_ticket_email` from `app.worker`
- Produces: `TicketTool(db)` with `name = "create_ticket"`, `call({"subject": str, "body": str, "conversation_id": int|None}) -> dict`

- [ ] **Step 1: Write failing test**

Create `tests/test_ticket_tool.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base
from app.tools.ticket import TicketTool


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_ticket_created(db_session):
    with patch("app.tools.ticket.send_ticket_email") as mock_task:
        mock_task.delay = MagicMock()
        tool = TicketTool(db_session)
        result = await tool.call({"subject": "Panel broken", "body": "My panel stopped working after 2 days."})
    assert "ticket_id" in result
    assert result["status"] == "open"
    assert "confirmation" in result
    mock_task.delay.assert_called_once()


@pytest.mark.asyncio
async def test_ticket_with_conversation_id(db_session):
    from app.db.models import Conversation
    conv = Conversation(session_id="sess-abc", language="fr")
    db_session.add(conv)
    await db_session.flush()

    with patch("app.tools.ticket.send_ticket_email") as mock_task:
        mock_task.delay = MagicMock()
        tool = TicketTool(db_session)
        result = await tool.call({
            "subject": "Livraison retardée",
            "body": "Ma commande est en retard.",
            "conversation_id": conv.id,
        })
    assert result["ticket_id"] is not None


def test_definition():
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def _run():
        async with Session() as s:
            tool = TicketTool(s)
            defn = tool.definition()
            assert defn["function"]["name"] == "create_ticket"
            props = defn["function"]["parameters"]["properties"]
            assert "subject" in props
            assert "body" in props
    asyncio.run(_run())
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_ticket_tool.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.tools.ticket'`

- [ ] **Step 3: Write app/tools/ticket.py**

```python
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

        send_ticket_email.delay(ticket.id, subject, body)

        return {
            "ticket_id": ticket.id,
            "status": ticket.status,
            "confirmation": f"Support ticket #{ticket.id} created. Our team will contact you shortly.",
        }
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_ticket_tool.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/tools/ticket.py tests/test_ticket_tool.py
git commit -m "feat: TicketTool — create ticket + async Celery email to admin"
```

---

## Task 7: Tool Registry + Orchestrator Update

**Files:**
- Modify: `app/tools/__init__.py`
- Modify: `app/agent/orchestrator.py`

**Interfaces:**
- Consumes: `CurrencyTool`, `LogisticsTool` (no db); `QuoteTool`, `OrderTool`, `TicketTool` (need db)
- Produces: `get_tools(db) -> list[BaseTool]`; `get_tool_map(db) -> dict[str, BaseTool]` from `app.tools`

**Note:** DB-dependent tools need a session at call time. The registry provides factory functions so the orchestrator can build the list per-request.

- [ ] **Step 1: Write app/tools/__init__.py**

```python
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
```

- [ ] **Step 2: Update app/agent/orchestrator.py imports**

Replace line:
```python
from app.tools.currency import TOOLS, TOOL_MAP
```
With:
```python
from app.tools import get_tools, get_tool_map
```

Then replace usage in `run()`:
```python
tool_defs = [t.definition() for t in TOOLS]
```
With:
```python
tools_list = get_tools(db)
tool_defs = [t.definition() for t in tools_list]
tool_map = get_tool_map(db)
```

And replace:
```python
tool = TOOL_MAP.get(tool_name)
```
With:
```python
tool = tool_map.get(tool_name)
```

- [ ] **Step 3: Run full test suite to verify nothing broke**

```bash
pytest tests/ -v --ignore=tests/test_websocket.py --ignore=tests/test_admin_auth.py --ignore=tests/test_admin_routes.py
```

Expected: all existing tests PASS.

- [ ] **Step 4: Commit**

```bash
git add app/tools/__init__.py app/agent/orchestrator.py
git commit -m "feat: tool registry — 5 tools unified; orchestrator updated"
```

---

## Task 8: LLM Streaming + WebSocket Endpoint

**Files:**
- Modify: `app/llm/client.py` — add `chat_complete_stream()`
- Modify: `app/agent/orchestrator.py` — add `run_stream()`
- Create: `app/api/ws_manager.py`
- Create: `app/api/ws.py`
- Modify: `app/main.py`
- Test: `tests/test_websocket.py`

**Interfaces:**
- Produces:
  - `chat_complete_stream(messages, tools=None) -> AsyncGenerator[str, None]` in `app.llm.client`
  - `run_stream(message, session_id, db) -> AsyncGenerator[str, None]` in `app.agent.orchestrator`
  - `manager: ConnectionManager` singleton in `app.api.ws_manager`
  - Routes: `GET /ws/{conversation_id}`, `GET /ws/admin/{user_id}`

- [ ] **Step 1: Add streaming to app/llm/client.py**

Append to the file:

```python
from typing import AsyncGenerator


async def chat_complete_stream(
    messages: list[dict], tools: list[dict] | None = None
) -> AsyncGenerator[str, None]:
    client = get_client()
    kwargs: dict = {"model": LLM_MODEL, "messages": messages, "stream": True}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
```

- [ ] **Step 2: Add run_stream to app/agent/orchestrator.py**

Add this import at top:
```python
from typing import AsyncGenerator
from app.llm.client import chat_complete, chat_complete_stream
```
(replace the existing `from app.llm.client import chat_complete`)

Append to orchestrator.py:

```python
async def run_stream(
    message: str, session_id: str, db: AsyncSession
) -> AsyncGenerator[str, None]:
    """Streaming variant of run(). Yields reply tokens one at a time.
    Tool calls are resolved synchronously before streaming the final reply.
    """
    lang = detect_language(message)

    result = await db.execute(select(Conversation).where(Conversation.session_id == session_id))
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

    # Non-streaming first pass to detect tool calls
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
```

- [ ] **Step 3: Write app/api/ws_manager.py**

```python
from fastapi import WebSocket
from typing import Dict
import json


class ConnectionManager:
    def __init__(self):
        self.customer: Dict[int, WebSocket] = {}   # conv_id -> ws
        self.admin: Dict[int, WebSocket] = {}       # user_id -> ws

    async def connect_customer(self, conv_id: int, ws: WebSocket):
        await ws.accept()
        self.customer[conv_id] = ws

    async def connect_admin(self, user_id: int, ws: WebSocket):
        await ws.accept()
        self.admin[user_id] = ws

    def disconnect_customer(self, conv_id: int):
        self.customer.pop(conv_id, None)

    def disconnect_admin(self, user_id: int):
        self.admin.pop(user_id, None)

    async def send_to_customer(self, conv_id: int, data: dict):
        ws = self.customer.get(conv_id)
        if ws:
            await ws.send_text(json.dumps(data))

    async def send_to_admin(self, user_id: int, data: dict):
        ws = self.admin.get(user_id)
        if ws:
            await ws.send_text(json.dumps(data))

    async def broadcast_to_all_admins(self, data: dict):
        for ws in self.admin.values():
            await ws.send_text(json.dumps(data))


manager = ConnectionManager()
```

- [ ] **Step 4: Write app/api/ws.py**

```python
import json
import os
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.agent.orchestrator import run_stream
from app.api.ws_manager import manager

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def get_redis():
    return aioredis.from_url(REDIS_URL, decode_responses=True)


@router.websocket("/ws/{conversation_id}")
async def customer_ws(conversation_id: int, ws: WebSocket, db: AsyncSession = Depends(get_db)):
    await manager.connect_customer(conversation_id, ws)
    redis = get_redis()
    session_id = f"conv-{conversation_id}"
    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            message = data.get("message", "")

            mode = await redis.get(f"conv:{conversation_id}:mode") or "ai"

            if mode == "human":
                agent_id_str = await redis.get(f"conv:{conversation_id}:agent")
                if agent_id_str:
                    await manager.send_to_admin(int(agent_id_str), {
                        "type": "customer_message",
                        "conversation_id": conversation_id,
                        "text": message,
                    })
                    await manager.send_to_customer(conversation_id, {
                        "type": "status",
                        "text": "Message sent to your agent.",
                    })
            else:
                await manager.send_to_customer(conversation_id, {"type": "start"})
                async for token in run_stream(message, session_id, db):
                    await manager.send_to_customer(conversation_id, {
                        "type": "token",
                        "text": token,
                    })
                await manager.send_to_customer(conversation_id, {"type": "end"})
    except WebSocketDisconnect:
        manager.disconnect_customer(conversation_id)
        await redis.aclose()


@router.websocket("/ws/admin/{user_id}")
async def admin_ws(user_id: int, ws: WebSocket):
    await manager.connect_admin(user_id, ws)
    redis = get_redis()
    try:
        while True:
            text = await ws.receive_text()
            data = json.loads(text)
            action = data.get("action")

            if action == "takeover":
                conv_id = int(data["conversation_id"])
                await redis.set(f"conv:{conv_id}:mode", "human")
                await redis.set(f"conv:{conv_id}:agent", str(user_id))
                await manager.send_to_customer(conv_id, {
                    "type": "status",
                    "text": "You have been connected to a live agent.",
                })

            elif action == "release":
                conv_id = int(data["conversation_id"])
                await redis.set(f"conv:{conv_id}:mode", "ai")
                await redis.delete(f"conv:{conv_id}:agent")
                await manager.send_to_customer(conv_id, {
                    "type": "status",
                    "text": "You have been reconnected to the AI assistant.",
                })

            elif action == "message":
                conv_id = int(data["conversation_id"])
                await manager.send_to_customer(conv_id, {
                    "type": "agent_message",
                    "text": data.get("text", ""),
                })
    except WebSocketDisconnect:
        manager.disconnect_admin(user_id)
        await redis.aclose()
```

- [ ] **Step 5: Update app/main.py**

Replace the contents:

```python
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.api.chat import router as chat_router
from app.api.ws import router as ws_router

app = FastAPI(title="Rest Solar AI Agent")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(chat_router)
app.include_router(ws_router)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request=request, name="chat.html")


@app.get("/mobile", response_class=HTMLResponse)
async def mobile_page(request: Request):
    return templates.TemplateResponse(request=request, name="mobile.html")


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Write tests/test_websocket.py**

```python
import pytest
import json
from httpx import AsyncClient, ASGITransport
from httpx_ws import aconnect_ws
from app.main import app


@pytest.mark.asyncio
async def test_ws_connect_and_ai_reply(monkeypatch):
    tokens = ["Hello", " from", " AI"]

    async def fake_run_stream(message, session_id, db):
        for t in tokens:
            yield t

    monkeypatch.setattr("app.api.ws.run_stream", fake_run_stream)

    async def fake_redis_get(key):
        return None  # mode = ai

    import app.api.ws as ws_mod
    import unittest.mock as mock

    fake_redis = mock.AsyncMock()
    fake_redis.get = mock.AsyncMock(return_value=None)
    fake_redis.aclose = mock.AsyncMock()
    monkeypatch.setattr(ws_mod, "get_redis", lambda: fake_redis)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with aconnect_ws("/ws/1", client) as ws:
            await ws.send_text(json.dumps({"message": "hi"}))
            msg1 = json.loads(await ws.receive_text())
            assert msg1["type"] == "start"
            collected = []
            while True:
                msg = json.loads(await ws.receive_text())
                if msg["type"] == "end":
                    break
                if msg["type"] == "token":
                    collected.append(msg["text"])
            assert "".join(collected) == "Hello from AI"
```

Note: `httpx_ws` must be installed (`pip install httpx-ws`). Add to requirements.txt:
```
httpx-ws>=0.5.0
```

- [ ] **Step 7: Run websocket test**

```bash
pip install httpx-ws
pytest tests/test_websocket.py -v
```

Expected: 1 test PASSED.

- [ ] **Step 8: Commit**

```bash
git add app/llm/client.py app/agent/orchestrator.py app/api/ws_manager.py app/api/ws.py app/main.py tests/test_websocket.py requirements.txt
git commit -m "feat: WebSocket chat — token streaming, human takeover via Redis mode flag"
```

---

## Task 9: Admin Auth (JWT + Login)

**Files:**
- Create: `app/admin/__init__.py`
- Create: `app/admin/auth.py`
- Create: `app/admin/deps.py`
- Create: `app/admin/routes.py` (login/logout only)
- Create: `templates/admin/base.html`
- Create: `templates/admin/login.html`
- Modify: `app/main.py`
- Test: `tests/test_admin_auth.py`

**Interfaces:**
- Produces:
  - `hash_password(plain: str) -> str`; `verify_password(plain, hashed) -> bool` from `app.admin.auth`
  - `create_access_token(data: dict) -> str` from `app.admin.auth`
  - `get_current_admin(request) -> AdminUser` async dependency from `app.admin.deps`
  - Routes: `POST /admin/login`, `GET /admin/login`, `POST /admin/logout`

- [ ] **Step 1: Write failing test**

Create `tests/test_admin_auth.py`:

```python
import pytest
from app.admin.auth import hash_password, verify_password, create_access_token, decode_access_token


def test_password_hash_and_verify():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_create_and_decode_token():
    token = create_access_token({"sub": "1", "role": "agent"})
    payload = decode_access_token(token)
    assert payload["sub"] == "1"
    assert payload["role"] == "agent"


def test_expired_token_raises():
    from datetime import timedelta
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-1))
    with pytest.raises(Exception):
        decode_access_token(token)
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_admin_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.admin'`

- [ ] **Step 3: Write app/admin/__init__.py**

```python
```
(empty)

- [ ] **Step 4: Write app/admin/auth.py**

```python
import os
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "dev-insecure-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
```

- [ ] **Step 5: Write app/admin/deps.py**

```python
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError
from app.db.session import get_db
from app.db.models import AdminUser
from app.admin.auth import decode_access_token


async def get_current_admin(request: Request, db: AsyncSession = Depends(get_db)) -> AdminUser:
    token = request.cookies.get("admin_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    return user


async def require_superadmin(current_user: AdminUser = Depends(get_current_admin)) -> AdminUser:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin required")
    return current_user
```

- [ ] **Step 6: Write app/admin/routes.py (login/logout only for now)**

```python
from fastapi import APIRouter, Request, Form, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.db.models import AdminUser
from app.admin.auth import verify_password, create_access_token
from app.admin.deps import get_current_admin

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin/login.html", context={"error": None})


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AdminUser).where(AdminUser.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="admin/login.html",
            context={"error": "Invalid email or password"},
            status_code=401,
        )
    token = create_access_token({"sub": str(user.id), "role": user.role})
    resp = RedirectResponse(url="/admin/dashboard", status_code=302)
    resp.set_cookie("admin_token", token, httponly=True, samesite="lax")
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie("admin_token")
    return resp
```

- [ ] **Step 7: Write templates/admin/base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Rest Solar Admin{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body class="bg-gray-100 min-h-screen">
  <nav class="bg-blue-800 text-white px-6 py-3 flex justify-between items-center">
    <a href="/admin/dashboard" class="font-bold text-lg">Rest Solar Admin</a>
    <div class="flex gap-4 text-sm">
      <a href="/admin/conversations" class="hover:underline">Conversations</a>
      <a href="/admin/products" class="hover:underline">Products</a>
      <a href="/admin/orders" class="hover:underline">Orders</a>
      <a href="/admin/tickets" class="hover:underline">Tickets</a>
      <a href="/admin/rules" class="hover:underline">Rules</a>
      {% if current_user.role == "superadmin" %}
      <a href="/admin/users" class="hover:underline">Users</a>
      <a href="/admin/reports" class="hover:underline">Reports</a>
      {% endif %}
      <form action="/admin/logout" method="post" class="inline">
        <button type="submit" class="hover:underline">Logout</button>
      </form>
    </div>
  </nav>
  <main class="p-6">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 8: Write templates/admin/login.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Admin Login — Rest Solar</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 flex items-center justify-center min-h-screen">
  <div class="bg-white p-8 rounded shadow w-full max-w-sm">
    <h1 class="text-2xl font-bold mb-6 text-blue-800">Rest Solar Admin</h1>
    {% if error %}
    <div class="bg-red-100 text-red-700 p-3 rounded mb-4 text-sm">{{ error }}</div>
    {% endif %}
    <form action="/admin/login" method="post" class="flex flex-col gap-4">
      <input type="email" name="email" placeholder="Email" required
             class="border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
      <input type="password" name="password" placeholder="Password" required
             class="border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
      <button type="submit"
              class="bg-blue-800 text-white py-2 rounded hover:bg-blue-700 text-sm font-medium">
        Sign in
      </button>
    </form>
  </div>
</body>
</html>
```

- [ ] **Step 9: Include admin router in app/main.py**

Add import and include:
```python
from app.admin.routes import router as admin_router
# ... after existing includes:
app.include_router(admin_router)
```

- [ ] **Step 10: Run auth tests**

```bash
pytest tests/test_admin_auth.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 11: Commit**

```bash
git add app/admin/ templates/admin/ app/main.py tests/test_admin_auth.py
git commit -m "feat: admin auth — JWT httpOnly cookie, login/logout, bcrypt passwords"
```

---

## Task 10: Admin CRUD Routes + Pages

**Files:**
- Modify: `app/admin/routes.py` — add all remaining routes
- Create: `templates/admin/dashboard.html`
- Create: `templates/admin/conversations.html`
- Create: `templates/admin/conversation_detail.html`
- Create: `templates/admin/rules.html`
- Create: `templates/admin/products.html`
- Create: `templates/admin/orders.html`
- Create: `templates/admin/tickets.html`
- Create: `templates/admin/users.html`
- Create: `templates/admin/reports.html`
- Test: `tests/test_admin_routes.py`

**Interfaces:**
- Consumes: `get_current_admin`, `require_superadmin` from `app.admin.deps`
- Produces: all admin page routes + HTMX partial endpoints

- [ ] **Step 1: Write failing test**

Create `tests/test_admin_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base, AdminUser
from app.admin.auth import hash_password, create_access_token


@pytest.fixture
async def authed_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        user = AdminUser(email="admin@test.com", password_hash=hash_password("pass"), role="superadmin")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        token = create_access_token({"sub": str(user.id), "role": user.role})

    # Override the DB dependency to use the in-memory DB
    from app.db.session import get_db
    async def override_get_db():
        async with Session() as s:
            yield s
    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           cookies={"admin_token": token}) as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/admin/dashboard", follow_redirects=False)
    assert resp.status_code in (302, 303)


@pytest.mark.asyncio
async def test_dashboard_with_auth(authed_client):
    resp = await authed_client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert b"Dashboard" in resp.content


@pytest.mark.asyncio
async def test_conversations_page(authed_client):
    resp = await authed_client.get("/admin/conversations")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_products_crud(authed_client):
    resp = await authed_client.post("/admin/products", data={
        "name": "Solar Panel 400W", "sku": "SP-400",
        "price_cny": "1200", "price_xaf": "108000",
        "duty_rate": "0.30", "vat_rate": "0.1925",
        "weight_kg": "22", "stock": "10",
    }, follow_redirects=True)
    assert resp.status_code == 200

    resp2 = await authed_client.get("/admin/products")
    assert b"SP-400" in resp2.content


@pytest.mark.asyncio
async def test_rules_crud(authed_client):
    resp = await authed_client.post("/admin/rules", data={
        "name": "Test Rule", "trigger": "test keyword", "body": "Test response", "priority": "10"
    }, follow_redirects=True)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest tests/test_admin_routes.py -v
```

Expected: `404` or template-not-found errors.

- [ ] **Step 3: Add all remaining routes to app/admin/routes.py**

Append to the existing `routes.py`:

```python
from fastapi import APIRouter, Request, Form, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.db.session import get_db
from app.db.models import AdminUser, Conversation, Message, Rule, Product, Order, Ticket
from app.admin.auth import verify_password, create_access_token, hash_password
from app.admin.deps import get_current_admin, require_superadmin

# (keep the login/logout routes already there, add below)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    conv_count = (await db.execute(select(Conversation))).scalars().all()
    ticket_count = (await db.execute(select(Ticket).where(Ticket.status == "open"))).scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/dashboard.html",
        context={"current_user": current_user, "conv_count": len(conv_count), "open_tickets": len(ticket_count)},
    )


@router.get("/conversations", response_class=HTMLResponse)
async def conversations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Conversation).order_by(desc(Conversation.created_at)).limit(50))
    convs = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/conversations.html",
        context={"current_user": current_user, "conversations": convs},
    )


@router.get("/conversations/{conv_id}", response_class=HTMLResponse)
async def conversation_detail(
    conv_id: int, request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    msgs = []
    if conv:
        msg_result = await db.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
        )
        msgs = msg_result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/conversation_detail.html",
        context={"current_user": current_user, "conversation": conv, "messages": msgs},
    )


@router.get("/rules", response_class=HTMLResponse)
async def rules_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Rule).order_by(Rule.priority))
    rules = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/rules.html",
        context={"current_user": current_user, "rules": rules},
    )


@router.post("/rules", response_class=HTMLResponse)
async def create_rule(
    request: Request,
    name: str = Form(...), trigger: str = Form(""), body: str = Form(...), priority: int = Form(10),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    db.add(Rule(name=name, trigger=trigger, body=body, priority=priority))
    await db.commit()
    return RedirectResponse(url="/admin/rules", status_code=302)


@router.post("/rules/{rule_id}/delete")
async def delete_rule(
    rule_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if rule:
        await db.delete(rule)
        await db.commit()
    return RedirectResponse(url="/admin/rules", status_code=302)


@router.get("/products", response_class=HTMLResponse)
async def products_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Product))
    products = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/products.html",
        context={"current_user": current_user, "products": products},
    )


@router.post("/products")
async def create_product(
    request: Request,
    name: str = Form(...), sku: str = Form(...),
    price_cny: float = Form(...), price_xaf: float = Form(...),
    duty_rate: float = Form(0.30), vat_rate: float = Form(0.1925),
    weight_kg: float = Form(None), stock: int = Form(0),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    db.add(Product(
        name=name, sku=sku.upper(), price_cny=price_cny, price_xaf=price_xaf,
        duty_rate=duty_rate, vat_rate=vat_rate, weight_kg=weight_kg, stock=stock,
    ))
    await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.post("/products/{product_id}/delete")
async def delete_product(
    product_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if product:
        await db.delete(product)
        await db.commit()
    return RedirectResponse(url="/admin/products", status_code=302)


@router.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Order).order_by(desc(Order.created_at)))
    orders = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/orders.html",
        context={"current_user": current_user, "orders": orders},
    )


@router.post("/orders/{order_id}/status")
async def update_order_status(
    order_id: int, status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if order:
        order.status = status
        await db.commit()
    return RedirectResponse(url="/admin/orders", status_code=302)


@router.get("/tickets", response_class=HTMLResponse)
async def tickets_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Ticket).order_by(desc(Ticket.created_at)))
    tickets = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/tickets.html",
        context={"current_user": current_user, "tickets": tickets},
    )


@router.post("/tickets/{ticket_id}/close")
async def close_ticket(
    ticket_id: int, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
):
    result = await db.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one_or_none()
    if ticket:
        ticket.status = "closed"
        await db.commit()
    return RedirectResponse(url="/admin/tickets", status_code=302)


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request, db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    result = await db.execute(select(AdminUser))
    users = result.scalars().all()
    return templates.TemplateResponse(
        request=request, name="admin/users.html",
        context={"current_user": current_user, "users": users},
    )


@router.post("/users")
async def create_user(
    email: str = Form(...), password: str = Form(...), role: str = Form("agent"),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
):
    db.add(AdminUser(email=email, password_hash=hash_password(password), role=role))
    await db.commit()
    return RedirectResponse(url="/admin/users", status_code=302)


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request, current_user: AdminUser = Depends(require_superadmin),
):
    return templates.TemplateResponse(
        request=request, name="admin/reports.html",
        context={"current_user": current_user},
    )


@router.post("/reports/export")
async def trigger_export(
    current_user: AdminUser = Depends(require_superadmin),
):
    from app.worker import celery_app
    celery_app.send_task("app.worker.export_conversations_csv")
    return RedirectResponse(url="/admin/reports", status_code=302)
```

- [ ] **Step 4: Write all admin templates**

Create `templates/admin/dashboard.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Dashboard{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Dashboard</h1>
<div class="grid grid-cols-2 gap-4 max-w-lg">
  <div class="bg-white rounded shadow p-6 text-center">
    <div class="text-4xl font-bold text-blue-800">{{ conv_count }}</div>
    <div class="text-gray-500 mt-1 text-sm">Total Conversations</div>
  </div>
  <div class="bg-white rounded shadow p-6 text-center">
    <div class="text-4xl font-bold text-orange-500">{{ open_tickets }}</div>
    <div class="text-gray-500 mt-1 text-sm">Open Tickets</div>
  </div>
</div>
{% endblock %}
```

Create `templates/admin/conversations.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Conversations{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Conversations</h1>
<table class="w-full bg-white rounded shadow text-sm">
  <thead class="bg-gray-50 text-left">
    <tr>
      <th class="p-3">ID</th><th class="p-3">Session</th>
      <th class="p-3">Language</th><th class="p-3">Created</th><th class="p-3"></th>
    </tr>
  </thead>
  <tbody>
    {% for c in conversations %}
    <tr class="border-t">
      <td class="p-3">{{ c.id }}</td>
      <td class="p-3 font-mono text-xs">{{ c.session_id }}</td>
      <td class="p-3 uppercase">{{ c.language }}</td>
      <td class="p-3">{{ c.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
      <td class="p-3"><a href="/admin/conversations/{{ c.id }}" class="text-blue-600 hover:underline">View</a></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/admin/conversation_detail.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Conversation #{{ conversation.id }}{% endblock %}
{% block content %}
<div class="flex justify-between items-center mb-6">
  <h1 class="text-2xl font-bold">Conversation #{{ conversation.id }}</h1>
  <button onclick="takeover({{ conversation.id }})"
          class="bg-orange-500 text-white px-4 py-2 rounded text-sm hover:bg-orange-600">
    Take Over
  </button>
</div>
<div class="bg-white rounded shadow p-4 space-y-3 max-w-2xl">
  {% for m in messages %}
  <div class="{% if m.role == 'user' %}text-right{% endif %}">
    <span class="inline-block px-3 py-2 rounded text-sm
      {% if m.role == 'user' %}bg-blue-100{% elif m.role == 'assistant' %}bg-gray-100{% else %}bg-yellow-50 text-xs{% endif %}">
      {% if m.role == 'tool' %}<em>Tool: {{ m.tool_name }}</em> — {% endif %}{{ m.content }}
    </span>
  </div>
  {% endfor %}
</div>
<script>
function takeover(convId) {
  const ws = new WebSocket(`ws://localhost/ws/admin/{{ current_user.id }}`);
  ws.onopen = () => ws.send(JSON.stringify({action: "takeover", conversation_id: convId}));
}
</script>
{% endblock %}
```

Create `templates/admin/rules.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Rules{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-4">Rules</h1>
<form action="/admin/rules" method="post" class="bg-white rounded shadow p-4 mb-6 grid grid-cols-2 gap-3 max-w-2xl">
  <input name="name" placeholder="Rule name" required class="border rounded px-3 py-2 text-sm col-span-2">
  <input name="trigger" placeholder="Trigger keywords (comma-separated)" class="border rounded px-3 py-2 text-sm">
  <input name="priority" type="number" placeholder="Priority (10=high)" value="10" class="border rounded px-3 py-2 text-sm">
  <textarea name="body" placeholder="Rule body / response" required class="border rounded px-3 py-2 text-sm col-span-2 h-24"></textarea>
  <button type="submit" class="bg-blue-800 text-white py-2 rounded text-sm col-span-2">Add Rule</button>
</form>
<table class="w-full bg-white rounded shadow text-sm">
  <thead class="bg-gray-50 text-left">
    <tr><th class="p-3">Priority</th><th class="p-3">Name</th><th class="p-3">Trigger</th><th class="p-3"></th></tr>
  </thead>
  <tbody>
    {% for r in rules %}
    <tr class="border-t">
      <td class="p-3">{{ r.priority }}</td>
      <td class="p-3 font-medium">{{ r.name }}</td>
      <td class="p-3 text-gray-500">{{ r.trigger }}</td>
      <td class="p-3">
        <form action="/admin/rules/{{ r.id }}/delete" method="post" class="inline">
          <button type="submit" class="text-red-500 hover:underline text-xs">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/admin/products.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Products{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-4">Products</h1>
<form action="/admin/products" method="post" class="bg-white rounded shadow p-4 mb-6 grid grid-cols-3 gap-3 max-w-3xl">
  <input name="name" placeholder="Name" required class="border rounded px-3 py-2 text-sm col-span-2">
  <input name="sku" placeholder="SKU" required class="border rounded px-3 py-2 text-sm">
  <input name="price_cny" type="number" step="0.01" placeholder="Price CNY" required class="border rounded px-3 py-2 text-sm">
  <input name="price_xaf" type="number" step="0.01" placeholder="Price XAF" required class="border rounded px-3 py-2 text-sm">
  <input name="weight_kg" type="number" step="0.01" placeholder="Weight (kg)" class="border rounded px-3 py-2 text-sm">
  <input name="stock" type="number" placeholder="Stock" value="0" class="border rounded px-3 py-2 text-sm">
  <button type="submit" class="bg-blue-800 text-white py-2 rounded text-sm col-span-3">Add Product</button>
</form>
<table class="w-full bg-white rounded shadow text-sm">
  <thead class="bg-gray-50 text-left">
    <tr><th class="p-3">SKU</th><th class="p-3">Name</th><th class="p-3">CNY</th><th class="p-3">XAF</th><th class="p-3">Stock</th><th class="p-3"></th></tr>
  </thead>
  <tbody>
    {% for p in products %}
    <tr class="border-t">
      <td class="p-3 font-mono text-xs">{{ p.sku }}</td>
      <td class="p-3">{{ p.name }}</td>
      <td class="p-3">¥{{ "%.0f"|format(p.price_cny) }}</td>
      <td class="p-3">{{ "%.0f"|format(p.price_xaf) }} XAF</td>
      <td class="p-3">{{ p.stock }}</td>
      <td class="p-3">
        <form action="/admin/products/{{ p.id }}/delete" method="post" class="inline">
          <button type="submit" class="text-red-500 hover:underline text-xs">Delete</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/admin/orders.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Orders{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Orders</h1>
<table class="w-full bg-white rounded shadow text-sm">
  <thead class="bg-gray-50 text-left">
    <tr><th class="p-3">Order #</th><th class="p-3">Customer</th><th class="p-3">Status</th><th class="p-3">Created</th><th class="p-3">Update</th></tr>
  </thead>
  <tbody>
    {% for o in orders %}
    <tr class="border-t">
      <td class="p-3 font-mono text-xs">{{ o.order_number }}</td>
      <td class="p-3">{{ o.customer_name or "—" }}</td>
      <td class="p-3"><span class="bg-gray-100 px-2 py-1 rounded text-xs">{{ o.status }}</span></td>
      <td class="p-3">{{ o.created_at.strftime("%Y-%m-%d") }}</td>
      <td class="p-3">
        <form action="/admin/orders/{{ o.id }}/status" method="post" class="flex gap-2">
          <select name="status" class="border rounded px-2 py-1 text-xs">
            {% for s in ["pending","confirmed","shipped","delivered","cancelled"] %}
            <option value="{{ s }}" {% if o.status == s %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
          <button type="submit" class="text-blue-600 hover:underline text-xs">Save</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/admin/tickets.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Tickets{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Tickets</h1>
<table class="w-full bg-white rounded shadow text-sm">
  <thead class="bg-gray-50 text-left">
    <tr><th class="p-3">ID</th><th class="p-3">Subject</th><th class="p-3">Status</th><th class="p-3">Created</th><th class="p-3"></th></tr>
  </thead>
  <tbody>
    {% for t in tickets %}
    <tr class="border-t">
      <td class="p-3">#{{ t.id }}</td>
      <td class="p-3">{{ t.subject }}</td>
      <td class="p-3"><span class="{% if t.status == 'open' %}text-orange-600{% else %}text-gray-400{% endif %} text-xs font-medium">{{ t.status }}</span></td>
      <td class="p-3">{{ t.created_at.strftime("%Y-%m-%d %H:%M") }}</td>
      <td class="p-3">
        {% if t.status == "open" %}
        <form action="/admin/tickets/{{ t.id }}/close" method="post" class="inline">
          <button type="submit" class="text-blue-600 hover:underline text-xs">Close</button>
        </form>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/admin/users.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Users{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-4">Admin Users</h1>
<form action="/admin/users" method="post" class="bg-white rounded shadow p-4 mb-6 grid grid-cols-3 gap-3 max-w-xl">
  <input name="email" type="email" placeholder="Email" required class="border rounded px-3 py-2 text-sm">
  <input name="password" type="password" placeholder="Password" required class="border rounded px-3 py-2 text-sm">
  <select name="role" class="border rounded px-3 py-2 text-sm">
    <option value="agent">agent</option>
    <option value="superadmin">superadmin</option>
  </select>
  <button type="submit" class="bg-blue-800 text-white py-2 rounded text-sm col-span-3">Create User</button>
</form>
<table class="w-full bg-white rounded shadow text-sm">
  <thead class="bg-gray-50 text-left">
    <tr><th class="p-3">Email</th><th class="p-3">Role</th><th class="p-3">Created</th></tr>
  </thead>
  <tbody>
    {% for u in users %}
    <tr class="border-t">
      <td class="p-3">{{ u.email }}</td>
      <td class="p-3 text-xs font-medium {% if u.role == 'superadmin' %}text-blue-700{% endif %}">{{ u.role }}</td>
      <td class="p-3">{{ u.created_at.strftime("%Y-%m-%d") }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Create `templates/admin/reports.html`:
```html
{% extends "admin/base.html" %}
{% block title %}Reports{% endblock %}
{% block content %}
<h1 class="text-2xl font-bold mb-6">Reports</h1>
<div class="bg-white rounded shadow p-6 max-w-md">
  <h2 class="font-semibold mb-2">Export Conversations</h2>
  <p class="text-sm text-gray-500 mb-4">Triggers a Celery task to generate a CSV of all conversations. Check your email when complete.</p>
  <form action="/admin/reports/export" method="post">
    <button type="submit" class="bg-blue-800 text-white px-4 py-2 rounded text-sm">Trigger Export</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 5: Add export_conversations_csv task to app/worker.py**

Append to `app/worker.py`:

```python
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
```

- [ ] **Step 6: Run admin routes tests**

```bash
pytest tests/test_admin_routes.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 7: Commit**

```bash
git add app/admin/routes.py app/worker.py templates/admin/ tests/test_admin_routes.py
git commit -m "feat: admin backend — dashboard, conversations, rules, products, orders, tickets, users, reports"
```

---

## Task 11: Mobile-first UI + PWA

**Files:**
- Modify: `static/widget.js` — rewrite for WebSocket + responsive
- Create: `templates/mobile.html`
- Create: `static/manifest.json`
- Create: `static/sw.js`

**Interfaces:**
- `widget.js` connects to `GET /ws/{conversation_id}` instead of `POST /api/chat`
- `/mobile` page served by route added in Task 8

- [ ] **Step 1: Rewrite static/widget.js**

```javascript
(function () {
  const CONV_ID = Math.floor(Math.random() * 1000000);
  const isMobile = window.innerWidth < 768;
  let ws = null;
  let reconnectDelay = 1000;

  function createWidget() {
    const container = document.createElement('div');
    container.id = 'rs-chat-container';
    container.innerHTML = `
      <div id="rs-chat-bubble" style="
        position:fixed; bottom:24px; right:24px; width:56px; height:56px;
        background:#1e40af; border-radius:50%; display:flex; align-items:center;
        justify-content:center; cursor:pointer; box-shadow:0 4px 12px rgba(0,0,0,0.3); z-index:9999;">
        <svg width="24" height="24" fill="white" viewBox="0 0 24 24">
          <path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z"/>
        </svg>
      </div>
      <div id="rs-chat-window" style="
        display:none; position:fixed; z-index:9998; background:white;
        box-shadow:0 8px 32px rgba(0,0,0,0.2); flex-direction:column;
        ${isMobile
          ? 'top:0;left:0;right:0;bottom:0;border-radius:0;'
          : 'bottom:90px;right:24px;width:360px;height:500px;border-radius:16px;'}
      ">
        <div style="background:#1e40af;color:white;padding:16px;border-radius:${isMobile ? '0' : '16px 16px 0 0'};
                    display:flex;justify-content:space-between;align-items:center;">
          <span style="font-weight:600;font-size:16px;">Rest Solar Support</span>
          <button id="rs-close" style="background:none;border:none;color:white;font-size:20px;cursor:pointer;">✕</button>
        </div>
        <div id="rs-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px;"></div>
        <div style="padding:12px;border-top:1px solid #e5e7eb;display:flex;gap:8px;">
          <input id="rs-input" type="text" placeholder="Type a message…"
            style="flex:1;border:1px solid #d1d5db;border-radius:8px;padding:10px 14px;font-size:16px;outline:none;">
          <button id="rs-send" style="background:#1e40af;color:white;border:none;border-radius:8px;
                  padding:10px 16px;cursor:pointer;font-size:14px;">Send</button>
        </div>
      </div>
    `;
    document.body.appendChild(container);

    document.getElementById('rs-chat-bubble').onclick = openChat;
    document.getElementById('rs-close').onclick = closeChat;
    document.getElementById('rs-send').onclick = sendMessage;
    document.getElementById('rs-input').addEventListener('keydown', e => {
      if (e.key === 'Enter') sendMessage();
    });
  }

  function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${protocol}://${location.host}/ws/${CONV_ID}`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'start') {
        appendMessage('assistant', '');
      } else if (data.type === 'token') {
        appendToken(data.text);
      } else if (data.type === 'agent_message') {
        appendMessage('agent', data.text);
      } else if (data.type === 'status') {
        appendMessage('status', data.text);
      }
    };

    ws.onclose = () => {
      setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
        connectWS();
      }, reconnectDelay);
    };

    ws.onopen = () => { reconnectDelay = 1000; };
  }

  function openChat() {
    document.getElementById('rs-chat-window').style.display = 'flex';
    document.getElementById('rs-chat-bubble').style.display = 'none';
    if (!ws || ws.readyState !== WebSocket.OPEN) connectWS();
  }

  function closeChat() {
    document.getElementById('rs-chat-window').style.display = 'none';
    document.getElementById('rs-chat-bubble').style.display = 'flex';
  }

  function sendMessage() {
    const input = document.getElementById('rs-input');
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    appendMessage('user', text);
    ws.send(JSON.stringify({ message: text }));
    input.value = '';
  }

  let currentAssistantMsg = null;

  function appendMessage(role, text) {
    const msgs = document.getElementById('rs-messages');
    const div = document.createElement('div');
    div.style.cssText = `
      max-width:80%; padding:10px 14px; border-radius:12px; font-size:14px; line-height:1.5;
      ${role === 'user'
        ? 'align-self:flex-end;background:#1e40af;color:white;border-bottom-right-radius:4px;'
        : role === 'status'
        ? 'align-self:center;background:#f3f4f6;color:#6b7280;font-size:12px;'
        : 'align-self:flex-start;background:#f3f4f6;color:#111;border-bottom-left-radius:4px;'}
    `;
    div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    if (role === 'assistant') currentAssistantMsg = div;
    return div;
  }

  function appendToken(token) {
    if (!currentAssistantMsg) appendMessage('assistant', '');
    currentAssistantMsg.textContent += token;
    const msgs = document.getElementById('rs-messages');
    msgs.scrollTop = msgs.scrollHeight;
  }

  createWidget();
})();
```

- [ ] **Step 2: Write templates/mobile.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="theme-color" content="#1e40af">
  <title>Rest Solar Support</title>
  <link rel="manifest" href="/static/manifest.json">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f3f4f6; height: 100vh; display: flex; flex-direction: column; }
    header { background: #1e40af; color: white; padding: 16px 20px; font-weight: 600; font-size: 18px; }
    #messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
    .msg { max-width: 80%; padding: 12px 16px; border-radius: 18px; font-size: 15px; line-height: 1.5; }
    .msg.user { align-self: flex-end; background: #1e40af; color: white; border-bottom-right-radius: 4px; }
    .msg.assistant { align-self: flex-start; background: white; color: #111; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .msg.status { align-self: center; background: transparent; color: #6b7280; font-size: 12px; }
    footer { padding: 12px 16px; background: white; border-top: 1px solid #e5e7eb; display: flex; gap: 10px; }
    #input { flex: 1; border: 1px solid #d1d5db; border-radius: 24px; padding: 12px 18px; font-size: 16px; outline: none; }
    #input:focus { border-color: #1e40af; }
    #send { background: #1e40af; color: white; border: none; border-radius: 24px; padding: 12px 20px; font-size: 15px; cursor: pointer; }
    #offline-banner { display: none; background: #fef3c7; color: #92400e; text-align: center; padding: 8px; font-size: 13px; }
  </style>
</head>
<body>
  <header>Rest Solar Support</header>
  <div id="offline-banner">No connection — messages will send when reconnected</div>
  <div id="messages"></div>
  <footer>
    <input id="input" type="text" placeholder="Type a message…" autocomplete="off">
    <button id="send">Send</button>
  </footer>
  <script>
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js');
    }

    const CONV_ID = Math.floor(Math.random() * 1000000);
    let ws, reconnectDelay = 1000, currentMsg = null;

    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${protocol}://${location.host}/ws/${CONV_ID}`);
      ws.onopen = () => { reconnectDelay = 1000; document.getElementById('offline-banner').style.display = 'none'; };
      ws.onclose = () => {
        document.getElementById('offline-banner').style.display = 'block';
        setTimeout(() => { reconnectDelay = Math.min(reconnectDelay * 2, 30000); connect(); }, reconnectDelay);
      };
      ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.type === 'start') { addMsg('assistant', ''); }
        else if (data.type === 'token') { appendToken(data.text); }
        else if (data.type === 'agent_message' || data.type === 'status') { addMsg('status', data.text); }
      };
    }

    function addMsg(role, text) {
      const div = document.createElement('div');
      div.className = `msg ${role}`;
      div.textContent = text;
      document.getElementById('messages').appendChild(div);
      div.scrollIntoView();
      if (role === 'assistant') currentMsg = div;
      return div;
    }

    function appendToken(t) {
      if (!currentMsg) addMsg('assistant', '');
      currentMsg.textContent += t;
      currentMsg.scrollIntoView();
    }

    function send() {
      const input = document.getElementById('input');
      const text = input.value.trim();
      if (!text) return;
      addMsg('user', text);
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ message: text }));
      input.value = '';
    }

    document.getElementById('send').onclick = send;
    document.getElementById('input').addEventListener('keydown', e => { if (e.key === 'Enter') send(); });
    connect();
  </script>
</body>
</html>
```

- [ ] **Step 3: Write static/manifest.json**

```json
{
  "name": "Rest Solar Support",
  "short_name": "Rest Solar",
  "start_url": "/mobile",
  "display": "standalone",
  "background_color": "#f3f4f6",
  "theme_color": "#1e40af",
  "icons": [
    {
      "src": "/static/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    }
  ]
}
```

- [ ] **Step 4: Write static/sw.js**

```javascript
const CACHE = 'rs-v1';
const OFFLINE_URL = '/mobile';

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll([OFFLINE_URL, '/static/manifest.json']))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(OFFLINE_URL))
    );
  }
});
```

- [ ] **Step 5: Verify all tests still pass**

```bash
pytest tests/ -v --ignore=tests/test_websocket.py
```

Expected: all tests PASS. (WebSocket test requires httpx-ws and a running Redis mock — skip in CI if needed.)

- [ ] **Step 6: Commit**

```bash
git add static/widget.js static/manifest.json static/sw.js templates/mobile.html
git commit -m "feat: mobile UI — WebSocket widget.js + /mobile PWA + service worker"
```

---

## Task 12: Docker Smoke Test

**Goal:** Verify the full stack starts and the health endpoint responds.

- [ ] **Step 1: Create data directories**

```bash
mkdir -p data/sqlite data/chroma
```

- [ ] **Step 2: Copy .env.example to .env and set required vars**

```bash
cp .env.example .env
```

Edit `.env` — at minimum set:
```
LLM_API_KEY=your-openrouter-key
ADMIN_SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
```

- [ ] **Step 3: Build and start all services**

```bash
docker compose up --build -d
```

Expected: all 4 services start. Check with:
```bash
docker compose ps
```
Expected output shows `app`, `worker`, `nginx`, `redis` all `Up`.

- [ ] **Step 4: Health check**

```bash
curl http://localhost/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Admin first-user setup**

```bash
docker compose exec app python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db.models import Base, AdminUser
from app.admin.auth import hash_password

async def create_admin():
    engine = create_async_engine('sqlite+aiosqlite:///./data/rest_solar.db')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        s.add(AdminUser(email='admin@restsolar.com', password_hash=hash_password('changeme'), role='superadmin'))
        await s.commit()
    print('Admin user created: admin@restsolar.com / changeme')

asyncio.run(create_admin())
"
```

- [ ] **Step 6: Verify admin login**

Open `http://localhost/admin/login` in browser. Log in with `admin@restsolar.com` / `changeme`. Expected: redirects to `/admin/dashboard`.

- [ ] **Step 7: Final commit and tag**

```bash
git add data/.gitkeep 2>/dev/null || true
git commit -m "chore: Docker smoke test passed — Phase 2 complete"
git tag phase-2-complete
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered in task |
|---|---|
| Docker infrastructure (§9) | Task 1 |
| Products table (§4) | Task 2 |
| Order/Ticket/AdminUser tables (§4) | Task 2 |
| QuoteTool (§5) | Task 3 |
| LogisticsTool (§5) | Task 4 |
| OrderTool (§5) | Task 5 |
| TicketTool + Celery email (§5) | Task 6 |
| Tool registry / orchestrator (§5) | Task 7 |
| WebSocket streaming (§6) | Task 8 |
| Human takeover / Redis state (§6) | Task 8 |
| Admin auth + JWT (§7) | Task 9 |
| All admin routes listed in §7 | Task 10 |
| CSV export via Celery (§7) | Task 10 |
| Responsive widget.js (§8①) | Task 11 |
| /mobile PWA page (§8②) | Task 11 |
| Service worker offline screen (§8②) | Task 11 |
| Docker smoke test (§10) | Task 12 |

**Gaps identified and fixed:**
- `export_conversations_csv` Celery task was in spec but missing — added in Task 10 Step 5.
- `httpx-ws` test dependency added to requirements.txt in Task 8.
- First-admin-user CLI script not in spec but needed to bootstrap — added in Task 12 Step 5.

**Type consistency verified:**
- `QuoteTool(db)`, `OrderTool(db)`, `TicketTool(db)` — all take `AsyncSession`, consistent Task 3-6 through Task 7 registry.
- `run_stream(message, session_id, db)` — defined Task 8, matches signature used in `ws.py`.
- `send_ticket_email.delay(ticket_id, subject, body)` — defined Task 1, used Task 6, matches signature.
- `get_tools(db)` / `get_tool_map(db)` — defined Task 7, used in updated orchestrator Task 7.
