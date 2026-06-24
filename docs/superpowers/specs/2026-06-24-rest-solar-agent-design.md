# Rest Solar AI Customer Service Agent — Design Spec
**Date:** 2026-06-24
**Status:** Approved

---

## 1. Overview

A bilingual (English + French) AI customer-service agent for **Rest Solar**, a solar-products company selling from China into Cameroon. The agent answers customer questions from a proprietary knowledge base (RAG), enforces hard business rules, and calls tools (currency conversion, quotes, logistics, orders, support tickets). It embeds as a chat widget on the existing `camaroom-web` static site.

Built in two phases:
- **Phase 1** — Minimal runnable demo: Rails + ChromaDB RAG + OpenRouter LLM + CNY↔XAF currency tool + bilingual chat page
- **Phase 2** — Full commercial version: admin backend, all tools, ActionCable WebSocket, mobile-first UI, Sidekiq jobs, Devise auth

---

## 2. Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Ruby 3.2 via rbenv | System Ruby 2.6 is too old for Rails 7 |
| Framework | Rails 7 (API + minimal views) | From day 1 — no Sinatra migration later |
| Database | SQLite (dev) / PostgreSQL (prod) | 3 tables: conversations, messages, rules |
| Vector DB | ChromaDB | Docker container, local HTTP on port 8000 |
| Embeddings | Jina AI (`jina-embeddings-v3`) | Free tier 1M tokens/month, excellent EN+FR |
| LLM | OpenRouter (`google/gemini-flash-1.5`) | Configurable; upgradeable via env var |
| HTTP client | Faraday + faraday-retry | All external calls: OpenRouter, Jina, ChromaDB, currency API |
| Widget | Vanilla JS + TailwindCSS CDN | Embeddable `<script>` tag, no build step |
| Background jobs | Sidekiq (Phase 2) | Ticket emails, report generation |
| Admin auth | Devise (Phase 2) | Role-based access |
| Realtime | ActionCable WebSocket (Phase 2) | Phase 1 uses HTTP polling |

---

## 3. Architecture

Every incoming customer message passes through four layers in sequence:

```
Customer message
       │
       ▼
┌─────────────────────┐
│   Rule Engine       │  PostgreSQL rules table — hard guardrails checked first.
│   (Rails model)     │  E.g. "never invent a price", "VAT = 19.25%", score threshold.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   RAG Retriever     │  Embeds query via Jina AI → queries ChromaDB →
│   (Service object)  │  returns top-3 document chunks as grounding context.
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   LLM Orchestrator  │  Builds prompt (system rules + retrieved chunks +
│   (OpenRouter)      │  conversation history + user message) → calls
│                     │  OpenRouter (gemini-flash-1.5 by default).
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│   Tool Dispatcher   │  LLM may emit a tool call (currency, quote, order…).
│   (Phase 1: 1 tool) │  Rails executes the tool and feeds result back to LLM.
└────────┬────────────┘
         │
         ▼
     Response (EN or FR, matching input language)
```

ChromaDB runs as a Docker container. Rails talks to it over local HTTP. No LLM calls happen client-side — the OpenRouter key never leaves the server.

---

## 4. Agent Pipeline (step-by-step)

1. **Detect language** — regex heuristic on French accent chars + common words → `"fr"` or `"en"`
2. **Load rules** — query `rules` table for active rules matching the query topic; append to system prompt
3. **RAG retrieval** — embed query via Jina AI → query ChromaDB top-3 chunks (score ≥ 0.5). If no chunks found: rule fires → decline to answer, offer support ticket
4. **Build messages array** — `[system_prompt, ...last_10_messages, retrieved_chunks_as_context, user_message]`
5. **Call OpenRouter** — POST with tool definitions (Phase 1: currency tool only)
6. **Tool dispatch** — if LLM returns `tool_call`: execute tool in Rails, append result as `"tool"` role message, re-call OpenRouter for final response
7. **Persist** — save user + assistant messages to DB
8. **Return** — JSON response; language matches input

---

## 5. Data Models

### `conversations`
| Column | Type | Notes |
|---|---|---|
| id | integer PK | |
| session_id | string | Browser-generated UUID |
| language | string | `"en"` or `"fr"` |
| created_at | datetime | |

### `messages`
| Column | Type | Notes |
|---|---|---|
| id | integer PK | |
| conversation_id | FK | |
| role | string | `"user"` / `"assistant"` / `"tool"` |
| content | text | |
| tool_name | string | Populated when role = `"tool"` |
| created_at | datetime | |

### `rules`
| Column | Type | Notes |
|---|---|---|
| id | integer PK | |
| name | string | Human label e.g. `"no_invented_prices"` |
| trigger | string | Keyword/topic that activates this rule |
| body | text | Rule text injected into system prompt |
| priority | integer | Lower = checked first |
| active | boolean | |
| created_at | datetime | |

ChromaDB holds a `knowledge_base` collection — chunks have metadata `{source_file, language, chunk_index}`. No ActiveRecord model for KB chunks; Rails talks to ChromaDB via HTTP service objects only.

---

## 6. File Structure

```
rest-solar-agent/
├── app/
│   ├── controllers/api/chat_controller.rb   # POST /api/chat
│   ├── models/
│   │   ├── conversation.rb
│   │   ├── message.rb
│   │   └── rule.rb
│   ├── services/
│   │   ├── agent/
│   │   │   ├── orchestrator.rb       # main pipeline (steps 1-8)
│   │   │   ├── rule_engine.rb        # loads matching rules
│   │   │   └── language_detector.rb  # en/fr heuristic
│   │   ├── rag/
│   │   │   ├── chroma_client.rb      # raw ChromaDB HTTP calls
│   │   │   ├── embedder.rb           # Jina AI embedding call
│   │   │   └── retriever.rb          # embed → query → top-k chunks
│   │   ├── llm/
│   │   │   └── openrouter_client.rb  # chat completion + tool call handling
│   │   └── tools/
│   │       ├── base_tool.rb          # shared .definition interface
│   │       └── currency_tool.rb      # CNY ↔ XAF (Phase 1)
│   └── views/chat/index.html.erb     # demo chat page
├── db/
│   ├── migrate/                      # 3 migrations
│   └── seeds.rb                      # seed rules + FAQs into ChromaDB
├── lib/tasks/kb.rake                 # rake kb:import[path/to/file]
├── public/widget.js                  # embeddable <script> widget
├── config/routes.rb
├── docker-compose.yml                # ChromaDB on port 8000
├── .env
├── .env.example
├── .gitignore
└── Gemfile
```

---

## 7. Gems

### Phase 1
```ruby
gem "faraday"          # HTTP for OpenRouter, Jina, ChromaDB, currency API
gem "faraday-retry"    # auto-retry on transient errors
gem "dotenv-rails"     # load .env
gem "pdf-reader"       # parse PDFs for KB import
gem "rubyXL"           # parse Excel price sheets
gem "nokogiri"         # parse web-scraped HTML docs
```

### Phase 2 additions
```ruby
gem "devise"           # admin auth
gem "sidekiq"          # background jobs
gem "kaminari"         # pagination
gem "chartkick"        # conversation stats charts
```

---

## 8. Tools

All tools follow a common interface:
- `.definition` → returns OpenAI-compatible JSON schema (for the LLM tool call spec)
- `.call(params)` → executes the tool, returns a hash

| Tool | Phase | Notes |
|---|---|---|
| `CurrencyTool` | 1 | CNY↔XAF via configurable rate API; static fallback if `CURRENCY_API_KEY` unset |
| `QuoteTool` | 2 | quantity → subtotal + duty + VAT + shipping |
| `LogisticsTool` | 2 | China→Cameroon sea/air time + freight (stubbed) |
| `OrderTool` | 2 | order number → status from orders table |
| `TicketTool` | 2 | create support ticket row + email admin via Sidekiq |

---

## 9. Knowledge Base Import

`rake kb:import[path/to/file]` accepts:
- `.pdf` → extracted via `pdf-reader`
- `.xlsx` → extracted via `rubyXL`
- `.html` / URL → extracted via `nokogiri`
- `.txt` → read directly

Each file is chunked (~500 tokens, 50-token overlap), embedded via Jina AI, and upserted into ChromaDB with `{source_file, language, chunk_index}` metadata.

---

## 10. Anti-Hallucination Rules (seeded)

| Rule name | Trigger | Body |
|---|---|---|
| `no_invented_prices` | price / tariff / duty / VAT | "You MUST only quote prices and duties from the retrieved knowledge base chunks. If no price is found in context, say you don't have that information and offer a support ticket." |
| `cameroon_vat` | VAT / tax / taxe | "Cameroon VAT is 19.25%. Never state a different rate unless a KB chunk explicitly overrides it." |
| `low_score_fallback` | (always active) | "If no relevant knowledge base chunks were retrieved (score < 0.5), do not attempt to answer from general knowledge. Say you don't have specific information and offer to raise a support ticket." |

---

## 11. Phase 1 Scope

### In scope
- rbenv + Ruby 3.2 setup
- Rails 7 app at `~/rest-solar-agent`
- ChromaDB via `docker-compose up`
- 3 DB migrations + seeds (rules + FAQs)
- Full agent pipeline (language detect → rule engine → RAG → OpenRouter → tool dispatch)
- `CurrencyTool` — CNY↔XAF with static fallback
- 5 EN + 5 FR solar product FAQ chunks seeded into ChromaDB
- `rake kb:import` CLI
- Demo chat page at `http://localhost:3000/chat`
- `public/widget.js` embeddable on any HTML page

### Out of scope for Phase 1
- Admin backend, Devise, Sidekiq
- Logistics, quote, order, ticket tools
- File upload in widget
- Mobile optimisation
- ActionCable (HTTP polling used instead)

---

## 12. Phase 1 Test Checklist

1. `docker-compose up -d` → ChromaDB healthy at `localhost:8000`
2. `rails db:seed` → rules + FAQs loaded with no errors
3. Open `localhost:3000/chat` → ask English solar FAQ → grounded answer citing KB
4. Ask a French question → reply comes back in French
5. Ask "convert 500 CNY to XAF" → currency tool fires, returns correct calculation
6. Ask an invented price question → agent refuses to invent, offers ticket

---

## 13. Deployment Notes (future)

- Target VPS in Europe (good Cameroon latency), HTTPS via SSL cert, CDN for static assets
- Server-side OpenRouter calls only — key never exposed to client
- All customer conversations + docs stored in our own DB, not a third-party platform
- ChromaDB volume-mounted for persistence across container restarts
