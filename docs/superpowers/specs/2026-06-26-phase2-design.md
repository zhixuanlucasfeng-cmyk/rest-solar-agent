# Rest Solar Agent — Phase 2 Design Spec

**Date:** 2026-06-26  
**Branch:** phase-2-build (to be created)  
**Builds on:** Phase 1 complete (`phase-1-complete` tag)

---

## 1. Overview

Phase 2 promotes the Phase 1 demo into a production-ready deployment. It adds Docker Compose packaging, four new AI tools, WebSocket realtime chat with human takeover, a full admin backend, and a mobile-first UI — all built on top of the existing FastAPI + ChromaDB + SQLite foundation without rewriting it.

---

## 2. Architecture

Docker Compose orchestrates four services:

```
┌─────────────────────────────────────────────────────┐
│                  Docker Compose                      │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  nginx   │  │   app    │  │     worker       │  │
│  │ :80/:443 │→ │ FastAPI  │  │ Celery (emails,  │  │
│  └──────────┘  │ :8000    │  │  reports)        │  │
│                └────┬─────┘  └────────┬─────────┘  │
│                     │                 │             │
│                  ┌──┴─────────────────┴──┐          │
│                  │       redis :6379      │          │
│                  └───────────────────────┘          │
└─────────────────────────────────────────────────────┘
```

- **nginx** — reverse proxy for FastAPI, SSL termination, static file serving
- **app** — existing FastAPI app + all Phase 2 features
- **worker** — Celery worker for async tasks (email, CSV reports)
- **redis** — Celery broker + WebSocket conversation state

Phase 1 data (SQLite, ChromaDB, `.venv`) is mounted as Docker volumes. No existing code is rewritten.

---

## 3. Build Order

| # | Module | Description |
|---|--------|-------------|
| 1 | **Docker infrastructure** | Dockerfile, docker-compose.yml, nginx.conf, Celery config |
| 2 | **Products table + QuoteTool** | SQLite products table, quantity → price + duty + VAT + shipping |
| 3 | **LogisticsTool** | China→Cameroon sea/air transit time + freight (stubbed, interface ready) |
| 4 | **OrderTool** | orders table, order number → status lookup |
| 5 | **TicketTool** | tickets table, create ticket + async email to admin via Celery |
| 6 | **WebSocket realtime chat** | Replace HTTP POST, AI streaming, human takeover |
| 7 | **Admin backend** | JWT auth, user/role management, dashboard, conversations, rules, reports |
| 8 | **Mobile-first UI** | Responsive widget.js rewrite + standalone `/mobile` PWA page |

---

## 4. Database Schema (new tables)

All tables added via `create_all()` — no Alembic.

```sql
-- QuoteTool data source
products (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  sku           TEXT UNIQUE NOT NULL,
  price_cny     REAL NOT NULL,
  price_xaf     REAL NOT NULL,
  duty_rate     REAL DEFAULT 0.30,
  vat_rate      REAL DEFAULT 0.1925,
  weight_kg     REAL,
  stock         INTEGER DEFAULT 0
)

-- OrderTool data source
orders (
  id            INTEGER PRIMARY KEY,
  order_number  TEXT UNIQUE NOT NULL,
  customer_name TEXT,
  status        TEXT DEFAULT 'pending',
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
)

-- TicketTool output
tickets (
  id              INTEGER PRIMARY KEY,
  conversation_id INTEGER REFERENCES conversations(id),
  subject         TEXT NOT NULL,
  body            TEXT NOT NULL,
  status          TEXT DEFAULT 'open',
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
)

-- Admin backend auth
admin_users (
  id            INTEGER PRIMARY KEY,
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT DEFAULT 'agent',   -- 'superadmin' | 'agent'
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

---

## 5. New Tools

All tools implement the existing `BaseTool` ABC from `app/tools/base.py`.

| Tool | Input | Output |
|------|-------|--------|
| `QuoteTool` | product SKU + quantity | subtotal, duty, VAT, shipping, total (CNY + XAF) |
| `LogisticsTool` | origin city, destination, weight | sea/air transit days + freight cost (stubbed) |
| `OrderTool` | order number | status, customer name, created date |
| `TicketTool` | subject + body | ticket ID, confirmation; Celery sends email to admin |

---

## 6. WebSocket Realtime Chat + Human Takeover

**Endpoint:** `GET /ws/{conversation_id}`

**Flow:**
```
Customer Browser          FastAPI                Admin Dashboard
     │                      │                          │
     │── WS connect ────────→│                          │
     │── send message ───────→│                          │
     │                      │── stream tokens ──────────→│ (live view)
     │←── token by token ───│                          │
     │                      │                          │
     │                      │←── "takeover" ───────────│
     │                      │  (sets mode=human)        │
     │←── "Transferred to agent" ──│                   │
     │── send message ───────→│                          │
     │                      │──── forward ──────────────→│
     │←──────────── agent reply ────────────────────────│
```

**State (Redis):**
- `conv:{id}:mode` — `ai` | `human`
- `conv:{id}:agent` — agent user ID (when human mode)
- `active_convs` — set of active conversation IDs (for dashboard)

**Behavior:**
- AI mode: LLM streams tokens directly to customer WebSocket
- Human mode: messages forwarded to agent's Admin WebSocket; agent replies pushed to customer
- Any agent can claim an unclaimed conversation from the dashboard
- On WebSocket disconnect: mode resets to `ai` after 5 min timeout (Celery delayed task)

---

## 7. Admin Backend

**Base route:** `/admin`  
**Auth:** JWT stored in httpOnly cookie, validated per request  
**Frontend:** Jinja2 templates + HTMX (no React; lightweight realtime via partial page swaps)

**Routes:**

| Route | Role | Description |
|-------|------|-------------|
| `/admin/login` | public | Email + password login |
| `/admin/dashboard` | agent+ | Live stats + active conversation list with takeover button |
| `/admin/conversations` | agent+ | History, search, filter by date/language |
| `/admin/conversations/{id}` | agent+ | Full transcript + live takeover |
| `/admin/rules` | agent+ | CRUD for rule engine entries |
| `/admin/products` | agent+ | Product price table management |
| `/admin/orders` | agent+ | Order list, status update |
| `/admin/tickets` | agent+ | Ticket list, open/close |
| `/admin/users` | superadmin | Create/deactivate admin users |
| `/admin/reports` | superadmin | Trigger CSV export via Celery, download when ready |

**Dashboard realtime:** Admin WebSocket at `/ws/admin/{user_id}` pushes:
- New incoming conversation events
- New message counts
- Takeover/release events

---

## 8. Mobile-first UI

### ① Responsive widget.js (rewrite)
- Same `static/widget.js` entry point — existing embed code unchanged
- CSS media query breakpoint at 768px:
  - **Mobile:** full-screen overlay, bottom input bar, large tap targets, 16px+ fonts
  - **Desktop:** bottom-right floating window (same as Phase 1)
- Switches from HTTP POST to WebSocket connection
- Auto-reconnect on disconnect (exponential backoff, max 30s)

### ② Standalone `/mobile` page
- Direct browser access, no iframe embedding
- PWA manifest + service worker: installable to home screen, offline "no connection" screen
- Same WebSocket backend, same conversation flow
- Optimized for low-bandwidth (Cameroon mobile networks): debounced typing indicator, compressed assets via nginx gzip

---

## 9. Docker Compose Structure

```
rest-solar-agent/
├── Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml      # overrides for production (SSL, env secrets)
├── nginx/
│   └── nginx.conf
├── app/
│   └── worker.py                # Celery app definition
└── .env.example                 # updated with REDIS_URL, SMTP_*, ADMIN_SECRET_KEY
```

**Volumes:**
- `./data/sqlite` → `/app/data` (SQLite database)
- `./data/chroma` → `/app/chroma_db` (ChromaDB)
- `~/.cache/huggingface` → `/root/.cache/huggingface` (model cache, avoid re-download)

---

## 10. Testing Strategy

Each module gets its own test file following Phase 1 patterns:

| Module | Test file | Key assertions |
|--------|-----------|----------------|
| QuoteTool | `tests/test_quote_tool.py` | correct subtotal, duty, VAT, total |
| LogisticsTool | `tests/test_logistics_tool.py` | returns transit days + freight |
| OrderTool | `tests/test_order_tool.py` | found/not-found cases |
| TicketTool | `tests/test_ticket_tool.py` | ticket created, Celery task enqueued |
| WebSocket | `tests/test_websocket.py` | connect, send, receive stream, takeover flow |
| Admin auth | `tests/test_admin_auth.py` | login, JWT validation, role enforcement |
| Admin routes | `tests/test_admin_routes.py` | CRUD operations per role |

Docker integration: `docker-compose.yml` tested with `docker compose up --build` smoke test in the final task.

---

## 11. Global Constraints

- Python 3.12, no version change
- SQLite + `create_all()` only — no Alembic in Phase 2
- No hardcoded secrets — all via `.env` / Docker environment
- Celery broker: Redis only (no RabbitMQ)
- Admin frontend: Jinja2 + HTMX only — no React/Vue/Next.js
- nginx config: gzip enabled, WebSocket `Upgrade` headers set
- All new tools implement `BaseTool` ABC without modification
