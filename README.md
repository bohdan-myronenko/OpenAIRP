# 🤖 OpenAIRP — Open AI Roleplay Platform

A self-hosted, Docker-based AI roleplay and chat platform that lets users create characters (bots), personas, and engage in conversations powered by any **OpenAI-compatible LLM API** — including local models via [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), [text-generation-webui](https://github.com/oobabooga/text-generation-webui), or cloud APIs like OpenAI and OpenRouter.

---

## ✨ Features

| Category | Details |
|---|---|
| **Chat** | Real-time streaming responses (SSE), message rerolling with attempt history, chat-specific generation overrides |
| **Bots** | Custom characters with persona, scenario, greeting, example dialog, avatar, and NSFW tagging |
| **Personas** | User-side character profiles usable across chats, with a default persona option |
| **Models** | Configurable LLM endpoints — bring your own API URL, key, and model name; per-model custom system prompts |
| **Generation Settings** | Temperature, top-p, max tokens, frequency/presence penalty, stop sequences — configurable at global, user, and chat level |
| **System Prompts** | Admin-managed reusable system prompts |
| **Admin Dashboard** | Streamlit-based dashboard for bot, user, model, and chat management |
| **Auth** | JWT + cookie-based authentication, user registration, admin roles |
| **File Storage** | Dedicated warehouse server for bot/persona avatars and uploaded assets |
| **Security** | HTTPS with TLS 1.2/1.3, HSTS, security headers, Nginx reverse proxy |

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Nginx Reverse Proxy                       │
│              (HTTPS termination, routing)                    │
│     :80 → redirect to :443    :443 → TLS                    │
├────────┬──────────┬───────────────┬──────────────────────────┤
│   /    │  /admin/ │  /api routes  │       /uploads/          │
│   ▼    │    ▼     │      ▼        │          ▼               │
│ Web UI │  Admin   │    API        │   Warehouse Server       │
│ :8501  │  :8502   │   :8080       │       :8080              │
└────────┴──────────┴───────┬───────┴──────────────────────────┘
                            │
                    ┌───────┴───────┐
                    │   Worker      │
                    │   :8081       │
                    │ (LLM proxy)   │
                    └───────────────┘
                            │
                    ┌───────┴───────┐
                    │  PostgreSQL   │
                    │   (Alpine)    │
                    └───────────────┘
```

### Services

| Service | Technology | Description |
|---|---|---|
| **Nginx** | Nginx (Alpine) | HTTPS reverse proxy with SSL termination, security headers, and route-based upstream selection |
| **API** | FastAPI + Uvicorn | Core REST API — user auth, bots, chats, messages, models, personas, system prompts |
| **Web UI** | Streamlit | User-facing chat interface with bot browsing, persona selection, model config, and streaming chat |
| **Admin Dashboard** | Streamlit | Admin-only interface for bot management, user accounts, chat monitoring, and model management |
| **Worker** | FastAPI | Stateless LLM proxy — receives structured prompts from the API and forwards them to any OpenAI-compatible endpoint (supports both standard and streaming SSE responses) |
| **Warehouse Server** | Nginx (Alpine) | Static file server for uploaded assets (bot/persona avatars) with CORS and caching |
| **Database** | PostgreSQL 15 (Alpine) | Persistent storage for all application data |

### Database Schema

Core tables: `users`, `bots`, `bot_tags`, `tags`, `personas`, `chats`, `messages`, `models`, `system_prompts`, `sessions`.

Key relationships:
- Users → Bots, Personas, Chats, Models (ownership)
- Chats → Messages (with reroll support via `parent_message_id` + `attempt_number`)
- Bots ↔ Tags (many-to-many)

---

## 🚀 Getting Started

### Prerequisites

- **Docker** and **Docker Compose** (v2+)
- **SSL certificates** (`cert.pem` and `key.pem`) placed in `nginx/ssl/`
  - For local/LAN use, you can generate a self-signed CA

### 1. Clone and Configure

```bash
git clone <repository-url>
cd OpenAIRP
```

Copy and edit the environment file:

```bash
cp .env.example .env
```

Configure the following in `.env`:

```env
# Database
DB_USER=orp_admin
DB_PASSWORD=<strong-password>
DB_NAME=orp_database

# Admin account (created on first run)
ADMIN_USERNAME=orp_admin
ADMIN_PASSWORD=<admin-password>

# Security
JWT_SECRET_KEY=<random-64-char-string>

# Network
USE_HTTPS=true
PUBLIC_API_URL=https://<your-ip-or-domain>
```

### 2. SSL Certificates

Place your SSL certificates in the `nginx/ssl/` directory:

```
nginx/ssl/
├── cert.pem
└── key.pem
```

For a self-signed certificate (development/LAN):

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem \
  -out nginx/ssl/cert.pem \
  -subj "/CN=localhost"
```

### 3. Build and Run

```bash
docker compose up -d --build
```

The platform will be available at:
- **Web UI**: `https://<your-host>/`
- **Admin Dashboard**: `https://<your-host>/admin/`
- **API Docs**: `https://<your-host>/docs`

### 4. Register & Log In

1. Open the Web UI and use the **Register New User** form to create your account.
2. Log in with your credentials.
3. Access the Admin Dashboard at `/admin/` using the admin credentials from `.env`.

---

## ⚙️ Configuration

### Adding LLM Models

1. Navigate to **⚙️ Models** in the Web UI (or **Models** in the Admin Dashboard).
2. Add a new model with:
   - **API URL** — the chat completions endpoint (e.g., `http://host.docker.internal:11434/v1/chat/completions` for Ollama)
   - **API Key** — your provider's API key (or any string for local models)
   - **Model Name** — the model identifier (e.g., `gpt-4o-mini`, `llama3`)
3. Set the model as **active** to use it for new chats.

### Generation Settings

Generation parameters can be configured at three levels (highest priority first):

1. **Chat-level** — per-chat overrides in the Chat Interface sidebar
2. **User-level** — user defaults in the Models page
3. **Global-level** — system-wide defaults managed by admins

Available parameters: `temperature`, `top_p`, `max_tokens`, `frequency_penalty`, `presence_penalty`, `stop` sequences.

---

## 📁 Project Structure

```
OpenAIRP/
├── docker-compose.yml          # Service orchestration
├── .env                        # Environment variables (secrets)
├── migrations/
│   └── init.sql                # Database schema (auto-runs on first start)
├── nginx/
│   ├── Dockerfile
│   ├── nginx.conf              # Reverse proxy configuration
│   └── ssl/                    # SSL certificates (gitignored)
├── warehouse-server/
│   ├── Dockerfile
│   └── nginx.conf              # Static file server config
├── services/
│   ├── api/                    # FastAPI backend
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── app/
│   │   │   ├── main.py         # App entry, middleware, startup
│   │   │   ├── auth.py         # JWT authentication
│   │   │   ├── db.py           # Database connection pool
│   │   │   ├── schemas.py      # Pydantic models
│   │   │   └── utils.py        # Shared utilities
│   │   └── routers/
│   │       ├── users.py        # User CRUD + auth endpoints
│   │       ├── bots.py         # Bot management
│   │       ├── chats.py        # Chat & message operations
│   │       ├── models.py       # LLM model configuration
│   │       ├── personas.py     # User persona management
│   │       ├── system_prompts.py
│   │       └── health.py
│   ├── web_ui/                 # Streamlit user interface
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── app.py          # Main app + auth + navigation
│   │       ├── api_client.py   # HTTP client for API
│   │       ├── auth.py         # Streamlit Authenticator integration
│   │       ├── state.py        # Session state management
│   │       ├── data_cache.py   # Data caching layer
│   │       └── views/
│   │           ├── home.py
│   │           ├── bots.py
│   │           ├── chats.py
│   │           ├── chat_interface.py   # Main chat view with streaming
│   │           ├── models.py
│   │           └── personas.py
│   ├── admin_dashboard/        # Streamlit admin interface
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py         # Dashboard entry + admin auth
│   │       ├── api_client.py
│   │       ├── auth.py
│   │       └── views/
│   │           ├── bots.py
│   │           ├── users.py
│   │           ├── chat_monitor.py
│   │           └── models.py
│   └── worker/                 # LLM generation worker
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/
│           └── main.py         # OpenAI-compatible API proxy
├── kb/                         # Knowledge base files (mounted read-only)
├── index/                      # Search index data
└── out/                        # Generated output (reports, etc.)
```

---

## 🐳 Docker Volumes

| Volume | Purpose | Backup Command |
|---|---|---|
| `postgres_data` | All database data (users, chats, messages, etc.) | `docker run --rm -v openairp_postgres_data:/data -v $(pwd):/backup alpine tar czf /backup/pg_backup.tar.gz /data` |
| `warehouse_data` | Uploaded files (avatars, assets) | `docker run --rm -v openairp_warehouse_data:/data -v $(pwd):/backup alpine tar czf /backup/wh_backup.tar.gz /data` |
| `auth_config` | Streamlit Authenticator config (shared between Web UI and Admin Dashboard) | — |

> ⚠️ **Important**: Use `docker compose down` (without `-v`) to preserve data. Using `-v` will **delete all volumes**.

---

## 🔧 Development

### Rebuilding a Single Service

```bash
docker compose up -d --build <service-name>
# e.g., docker compose up -d --build api
```

### Viewing Logs

```bash
docker compose logs -f <service-name>
# e.g., docker compose logs -f worker
```

### Networks

- **public** — Services accessible through Nginx (Web UI, API, Admin, Warehouse)
- **private** — Internal-only services (Worker, Database)

---

## 📜 License

This project is for personal/educational use.
