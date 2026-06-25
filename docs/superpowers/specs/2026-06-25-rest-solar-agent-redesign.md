# Rest Solar AI Customer Service Agent — Redesign Spec
**Date:** 2026-06-25
**Status:** Approved
**Supersedes:** `2026-06-24-rest-solar-agent-design.md`

---

## 1. Overview

A bilingual (English + French) AI customer-service agent for **Rest Solar**, a solar-products company selling from China into Cameroon. The agent answers customer questions from a proprietary knowledge base (RAG), enforces hard business rules, and calls tools (currency conversion, quotes, logistics, orders, support tickets). It embeds as a chat widget on the existing `camaroom-web` static site.

Built in two phases:
- **Phase 1** — Minimal runnable demo: Python/FastAPI + embedded ChromaDB + swappable LLM + CNY↔XAF currency tool + bilingual chat page
- **Phase 2** — Full commercial version: admin backend, all tools, WebSocket realtime, mobile-first UI, background jobs, auth

---

## 2. What Changed and Why

### 2.1 Ruby/Rails → Python + FastAPI
**Old:** Ruby 3.2 + Rails 7
**New:** Python 3.11+ + FastAPI

**Reason:** The entire RAG/LLM/agent ecosystem lives in Python — `sentence-transformers`, `chromadb`, `openai`, `langdetect` all have first-class Python support. The goal of this project is to build AI engineering skills, so the language should match the domain. FastAPI is the right Python web framework for this: async-native, auto-generates API docs, minimal boilerplate, and easy to extend.

### 2.2 Docker + ChromaDB server → ChromaDB PersistentClient (embedded)
**Old:** ChromaDB running as a Docker container, Rails calling it over HTTP on port 8000
**New:** `chromadb.PersistentClient(path="./data/chroma_db")` — runs in-process, writes to a local folder

**Reason:** For a dataset of ~10 FAQs + one product catalogue, a full Docker service is massive overkill. The embedded PersistentClient needs zero infrastructure: no Docker, no port, no service to start. The data persists on disk between restarts. When the dataset grows to thousands of documents, graduating to a Chroma server or Qdrant is a one-line config change.

### 2.3 LLM: old model → current model + swappable provider
**Old:** OpenRouter hardcoded to `google/gemini-flash-1.5`
**New:** OpenRouter defaulting to `google/gemini-3.1-flash-lite`, with full provider swap via `.env`

**Reason:** `gemini-flash-1.5` is outdated. More importantly, the LLM must be swappable because OpenRouter and Google APIs may be blocked in mainland China. Pointing the same code at a local Ollama instance (e.g. `gemma4`) requires changing only two env vars: `LLM_BASE_URL` and `LLM_MODEL`. The Python `openai` client speaks the same OpenAI-compatible protocol to all three providers (OpenRouter, Google AI Studio direct, Ollama).

**Provider config:**
```
# OpenRouter (default, global internet)
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-...
LLM_MODEL=google/gemini-3.1-flash-lite

# Local Ollama (China / offline)
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=gemma4
```

### 2.4 Embeddings: Jina AI cloud → sentence-transformers local (default)
**Old:** Jina AI cloud API (`jina-embeddings-v3`), requires `JINA_API_KEY`, blocked in China
**New:** `sentence-transformers` running in-process on CPU, no API key, no internet required

**Reason:** Local embeddings are free, work offline, work inside China, and run on CPU (no GPU needed for the model size chosen). The first run downloads the model (~420 MB); subsequent runs use the local cache. A cloud alternative (Gemini Embedding 2) is available via config for anyone who prefers it.

**Embedding config:**
```
# Local sentence-transformers (default)
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2

# Gemini cloud (alternative)
EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=AIza...
EMBEDDING_MODEL=models/text-embedding-004
```

---

## 3. Stack (Updated)

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | AI ecosystem is Python-native |
| Framework | FastAPI + Uvicorn | Async, auto docs, minimal boilerplate |
| Database | SQLite (dev) / PostgreSQL (prod) | SQLAlchemy ORM; same 3 tables as before |
| Vector DB | ChromaDB PersistentClient | In-process, no Docker, persists to `./data/chroma_db/` |
| Embeddings | sentence-transformers (local, default) | `paraphrase-multilingual-MiniLM-L12-v2`; Gemini Embedding 2 as cloud alt |
| LLM client | `openai` Python package | OpenAI-compat protocol; works with OpenRouter, Ollama, Google direct |
| LLM default | `google/gemini-3.1-flash-lite` via OpenRouter | Swap via `.env` — no code change needed |
| Widget | Vanilla JS + TailwindCSS CDN | Unchanged — embeddable `<script>` tag |
| Background jobs | FastAPI BackgroundTasks (Phase 1) / Celery+Redis (Phase 2) | Replaces Sidekiq |
| Admin auth | FastAPI + passlib + python-jose (Phase 2) | Replaces Devise |
| Realtime | FastAPI WebSocket (Phase 2) | Replaces ActionCable; Phase 1 uses HTTP POST |

---

## 4. Architecture

The pipeline is identical to the original design. Only the implementation language changes.

```
Customer message
       │
       ▼
┌─────────────────────┐
│   Rule Engine       │  SQLite rules table — hard guardrails checked first.
│   (Python class)    │  E.g. "never invent a price", "VAT = 19.25%".
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   RAG Retriever     │  Embeds query via sentence-transformers (local) →
│   (Python class)    │  queries ChromaDB PersistentClient →
│                     │  returns top-3 chunks (score ≥ 0.5).
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   LLM Orchestrator  │  Builds messages list (system prompt + rules +
│   (openai client)   │  retrieved chunks + history + user message) →
│                     │  calls LLM via OpenAI-compat API.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Tool Dispatcher   │  LLM may return a tool_call. FastAPI executes
│   (Phase 1: 1 tool) │  the tool and re-calls the LLM with the result.
└────────┬────────────┘
         │
         ▼
     Response (EN or FR, matching input language)
```

No client-side LLM calls. The API key (`LLM_API_KEY`) never leaves the server.

---

## 5. Agent Pipeline (step-by-step)

1. **Detect language** — `langdetect` library on the user message → `"fr"` or `"en"` (falls back to regex heuristic if `langdetect` is uncertain)
2. **Load rules** — query `rules` table for `active=True` rows whose `trigger` keyword appears in the message; append matched rule bodies to system prompt in priority order
3. **RAG retrieval** — embed query with sentence-transformers → query ChromaDB `knowledge_base` collection for top-3 chunks with cosine distance < 0.5. If none found: low-score rule fires → decline to answer, offer support ticket
4. **Build messages list** — `[{"role":"system", "content": system_prompt}, ...last_10_messages, {"role":"user", "content": f"Context:\n{chunks}\n\nQuestion: {message}"}]`
5. **Call LLM** — `openai.AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY).chat.completions.create(...)` with tool definitions
6. **Tool dispatch** — if response contains `tool_calls`: execute tool async, append `{"role":"tool", ...}` message, re-call LLM for final answer
7. **Persist** — save user + assistant messages to SQLite via SQLAlchemy
8. **Return** — `{"reply": "...", "language": "en"|"fr"}` JSON

---

## 6. Data Models (SQLAlchemy)

Same schema as the original design, expressed as SQLAlchemy models:

### `conversations`
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | auto-increment |
| session_id | String | Browser-generated UUID |
| language | String | `"en"` or `"fr"` |
| created_at | DateTime | default=`utcnow` |

### `messages`
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| conversation_id | FK → conversations | |
| role | String | `"user"` / `"assistant"` / `"tool"` |
| content | Text | |
| tool_name | String | nullable; populated when role=`"tool"` |
| created_at | DateTime | |

### `rules`
| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| name | String | e.g. `"no_invented_prices"` |
| trigger | String | keyword that activates this rule |
| body | Text | injected into system prompt |
| priority | Integer | lower = higher priority |
| active | Boolean | default True |
| created_at | DateTime | |

ChromaDB `knowledge_base` collection stores chunks with metadata `{source_file, language, chunk_index}`. No SQLAlchemy model for KB chunks — the retriever talks to ChromaDB directly in-process.

---

## 7. File Structure

```
rest-solar-agent/
├── app/
│   ├── main.py                    # FastAPI app, mounts routers
│   ├── api/
│   │   └── chat.py                # POST /api/chat endpoint
│   ├── agent/
│   │   ├── orchestrator.py        # main pipeline (steps 1-8 above)
│   │   ├── rule_engine.py         # queries rules table, returns matched bodies
│   │   └── language_detector.py   # langdetect + regex fallback
│   ├── rag/
│   │   ├── embedder.py            # sentence-transformers or Gemini, reads EMBEDDING_PROVIDER
│   │   └── retriever.py           # ChromaDB PersistentClient queries
│   ├── llm/
│   │   └── client.py              # openai.AsyncOpenAI, reads LLM_BASE_URL / LLM_MODEL
│   ├── tools/
│   │   ├── base.py                # BaseTool: definition() + async call()
│   │   └── currency.py            # CNY ↔ XAF, reads CURRENCY_API_KEY, static fallback
│   └── db/
│       ├── models.py              # SQLAlchemy: Conversation, Message, Rule
│       └── session.py             # async engine + get_db() dependency
├── data/
│   ├── seeds/
│   │   ├── faqs_en.txt            # 5 English FAQs (plain text, one Q&A per block)
│   │   └── faqs_fr.txt            # 5 French FAQs
│   └── chroma_db/                 # ChromaDB on-disk store (gitignored)
├── scripts/
│   └── kb_import.py               # python scripts/kb_import.py path/to/file
├── static/
│   └── widget.js                  # embeddable chat widget (vanilla JS)
├── templates/
│   └── chat.html                  # Jinja2 demo chat page
├── seed.py                        # python seed.py → loads rules + FAQs into DB + ChromaDB
├── .env
├── .env.example
├── .gitignore
└── requirements.txt
```

---

## 8. Python Packages

### Phase 1 (`requirements.txt`)
```
fastapi                          # web framework
uvicorn[standard]                # ASGI server
python-dotenv                    # load .env
openai                           # OpenAI-compat LLM client (OpenRouter / Ollama)
chromadb                         # embedded vector store (PersistentClient)
sentence-transformers            # local multilingual embeddings
langdetect                       # EN/FR language detection
sqlalchemy[asyncio]              # async ORM
aiosqlite                        # async SQLite driver
httpx                            # async HTTP for currency API
pypdf2                           # PDF parsing in kb_import
openpyxl                         # Excel parsing in kb_import
jinja2                           # HTML templates for demo chat page
python-multipart                 # form body parsing (FastAPI dependency)
```

### Phase 2 additions
```
celery[redis]                    # background jobs (ticket emails, reports)
redis                            # Celery broker
websockets                       # FastAPI WebSocket support
passlib[bcrypt]                  # password hashing for admin auth
python-jose[cryptography]        # JWT tokens for admin auth
```

---

## 9. Tools

All tools implement `BaseTool`:

```python
class BaseTool:
    name: str
    description: str

    def definition(self) -> dict:
        # Returns OpenAI-compatible tool schema for function calling
        ...

    async def call(self, params: dict) -> dict:
        # Executes the tool, returns result dict
        ...
```

| Tool | Phase | Notes |
|---|---|---|
| `CurrencyTool` | 1 | CNY↔XAF; hits a rate API if `CURRENCY_API_KEY` set, static fallback (1 CNY = ~90 XAF) otherwise |
| `QuoteTool` | 2 | quantity → subtotal + duty + VAT + shipping |
| `LogisticsTool` | 2 | China→Cameroon sea/air time + freight (stubbed API) |
| `OrderTool` | 2 | order number → status from orders table |
| `TicketTool` | 2 | creates ticket row + emails admin via Celery |

---

## 10. Knowledge Base Import CLI

```bash
python scripts/kb_import.py path/to/file.pdf
python scripts/kb_import.py path/to/prices.xlsx
python scripts/kb_import.py path/to/page.html
python scripts/kb_import.py path/to/notes.txt
```

**Import process:**
1. Detect file type by extension
2. Extract text (`pypdf2` for PDF, `openpyxl` for Excel, `BeautifulSoup` for HTML, plain read for `.txt`)
3. Chunk into ~500-token blocks with 50-token overlap
4. Embed each chunk via the configured `Embedder`
5. Upsert into ChromaDB `knowledge_base` collection with metadata `{source_file, language, chunk_index}`

The `language` metadata is detected per-chunk with `langdetect` so EN and FR documents can coexist in the same collection and be retrieved independently.

---

## 11. Anti-Hallucination Rules (seeded by `seed.py`)

| Rule name | Trigger keyword | Body injected into system prompt |
|---|---|---|
| `no_invented_prices` | price / tariff / duty / vat / prix / taxe | "You MUST only quote prices and duties from the retrieved knowledge-base chunks. If no price is found in context, say you don't have that information and offer a support ticket. Never invent a number." |
| `cameroon_vat` | vat / tax / taxe / tva | "Cameroon VAT is 19.25%. Never state a different rate unless a KB chunk explicitly overrides it." |
| `low_score_fallback` | (always active — priority 0) | "If no relevant knowledge-base chunks were retrieved (cosine distance > 0.5), do not attempt to answer from general knowledge. Say you don't have specific information and offer to raise a support ticket." |

---

## 12. Sample FAQs (seeded by `seed.py`)

**English (5):**
1. Q: What solar panel sizes do you sell? A: We stock panels from 50W to 550W monocrystalline...
2. Q: What warranty do your batteries come with? A: Lithium batteries carry a 2-year warranty...
3. Q: Do you deliver to cities outside Douala? A: Yes, we deliver across Cameroon...
4. Q: How long does a shipment from China take? A: Sea freight typically takes 30–45 days...
5. Q: What is the Cameroon import duty on solar panels? A: As of our last update, solar panels fall under HS code 8541.40 and attract a 10% import duty plus 19.25% VAT...

**French (5):**
1. Q: Quelles tailles de panneaux solaires vendez-vous ? R: Nous avons des panneaux de 50W à 550W monocristallins...
2. Q: Quelle garantie offrez-vous sur les batteries ? R: Les batteries lithium bénéficient d'une garantie de 2 ans...
3. Q: Livrez-vous en dehors de Douala ? R: Oui, nous livrons partout au Cameroun...
4. Q: Combien de temps prend une expédition depuis la Chine ? R: Le fret maritime prend généralement 30 à 45 jours...
5. Q: Quel est le droit d'importation au Cameroun pour les panneaux solaires ? R: Selon nos dernières informations, les panneaux solaires relèvent du code SH 8541.40 et sont soumis à 10 % de droits d'importation plus 19,25 % de TVA...

---

## 13. Phase 1 Scope

### In scope
- Python 3.11 virtual environment at `~/rest-solar-agent/`
- FastAPI app with `POST /api/chat` and demo `GET /chat` page
- ChromaDB PersistentClient (no Docker)
- sentence-transformers local embedding (auto-downloaded on first run)
- SQLite DB with 3 tables via SQLAlchemy
- `seed.py` — seeds 3 rules + 10 FAQs in one command
- Full agent pipeline: language detect → rule engine → RAG → LLM → tool dispatch
- `CurrencyTool` — CNY↔XAF with static fallback
- `scripts/kb_import.py` CLI for PDF/Excel/HTML/txt
- `static/widget.js` embeddable on any page
- `.env` with full provider-swap config

### Out of scope for Phase 1
- Admin backend, auth, background jobs
- Logistics, quote, order, ticket tools
- WebSocket (HTTP POST only in Phase 1)
- File upload in widget
- Mobile optimisation pass (widget is responsive but not tuned)
- Docker / production deployment

---

## 14. Phase 1 Build Order

1. **Python env** — confirm Python 3.11+, create `venv`, install `requirements.txt`
2. **Project skeleton** — create all folders, empty `__init__.py` files, `.env` from `.env.example`, `.gitignore`
3. **DB setup** — `app/db/models.py` (SQLAlchemy models) + `app/db/session.py` (async engine) → run `create_all()`
4. **Embedder** — `app/rag/embedder.py` reads `EMBEDDING_PROVIDER`; local path loads `sentence-transformers`
5. **ChromaDB retriever** — `app/rag/retriever.py` opens PersistentClient, wraps `collection.query()`
6. **Seed script** — `seed.py` inserts 3 rules into SQLite + embeds + upserts 10 FAQs into ChromaDB
7. **LLM client** — `app/llm/client.py` wraps `openai.AsyncOpenAI`, reads all three env vars
8. **Rule engine** — `app/agent/rule_engine.py` queries rules table by trigger keyword
9. **Language detector** — `app/agent/language_detector.py` wraps `langdetect` + regex fallback
10. **CurrencyTool** — `app/tools/currency.py` with static fallback
11. **Orchestrator** — `app/agent/orchestrator.py` wires steps 1–8 of the pipeline
12. **FastAPI app** — `app/main.py` + `app/api/chat.py` (`POST /api/chat`, `GET /chat`)
13. **Chat template** — `templates/chat.html` demo page with EN/FR toggle
14. **Widget** — `static/widget.js` embeddable `<script>` tag
15. **KB import CLI** — `scripts/kb_import.py` (PDF, Excel, HTML, txt)

---

## 15. Phase 1 Test Checklist

1. `python seed.py` → no errors; SQLite has 3 rules; ChromaDB has 10 chunks
2. `uvicorn app.main:app --reload` → server starts at `localhost:8000`
3. Open `http://localhost:8000/chat` → ask "What solar panels do you sell?" → grounded answer citing KB
4. Ask "Quels panneaux solaires vendez-vous ?" → reply comes back in French
5. Ask "convert 800 CNY to XAF" → CurrencyTool fires, returns calculation
6. Ask "What is the exact price of panel model X?" (not in KB) → agent says no info found, offers ticket
7. Switch `.env` to local Ollama, restart server → same test passes with local model

---

## 16. Deployment Notes (future, unchanged)

- Target VPS in Europe (good Cameroon latency), HTTPS, CDN for static assets
- Server-side LLM calls only — `LLM_API_KEY` never exposed to client
- All conversations + KB stored in our own DB, not a third-party platform
- ChromaDB data directory volume-mounted for persistence

---

## 17. Summary of Changes vs Original Design

| Concern | Original (2026-06-24) | Redesign (2026-06-25) |
|---|---|---|
| Language | Ruby 3.2 | Python 3.11+ |
| Framework | Rails 7 | FastAPI + Uvicorn |
| ORM | ActiveRecord | SQLAlchemy (async) |
| Vector DB infra | Docker + ChromaDB HTTP server | ChromaDB PersistentClient (in-process) |
| Embeddings | Jina AI cloud API | sentence-transformers (local CPU); Gemini as alt |
| LLM model | `google/gemini-flash-1.5` | `google/gemini-3.1-flash-lite` (swappable) |
| LLM provider swap | Not supported | Swap `LLM_BASE_URL + LLM_MODEL` in `.env` |
| HTTP client | Faraday (Ruby) | `openai` + `httpx` (Python) |
| Background jobs | Sidekiq (Phase 2) | Celery + Redis (Phase 2) |
| Admin auth | Devise (Phase 2) | passlib + python-jose (Phase 2) |
| Realtime | ActionCable (Phase 2) | FastAPI WebSocket (Phase 2) |
| Import CLI | `rake kb:import[file]` | `python scripts/kb_import.py file` |
| Seed command | `rails db:seed` | `python seed.py` |
| Package file | `Gemfile` | `requirements.txt` |

**Unchanged:** 4-layer pipeline architecture, 3 DB tables (same schema), 3 seeded anti-hallucination rules, 10 sample FAQs, CurrencyTool interface, widget.js (vanilla JS), Phase 1 scope boundary, deployment philosophy.

---

## 18. Final Decisions (all open questions resolved 2026-06-25)

| Question | Decision | Reason |
|---|---|---|
| Python version | **3.12** | Latest stable; all ML packages support it; no reason to use older |
| DB migrations | **`create_all()` for Phase 1**, Alembic later | One line to create tables; Alembic is for when schema changes frequently in production |
| Embedding model | **`paraphrase-multilingual-MiniLM-L12-v2` (420 MB)** | CPU inference, small dataset (catalogue + 10 FAQs); 1 GB model's quality gain is imperceptible at this scale |
| Phase 2 background jobs | **FastAPI `BackgroundTasks`** | No Docker/Redis overhead; built-in; switch to Celery only if ticket volume demands it |

**Spec status: FINAL — all decisions locked, ready for implementation.**
