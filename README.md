# RAG-Augmented Agentic PR Review Agent

[![CI](https://github.com/dhruvx05/rag-augmented-pr-review-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dhruvx05/rag-augmented-pr-review-agent/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

A **ReAct-pattern agentic AI** that autonomously reviews GitHub Pull Requests. The LLM decides which tools to invoke (Ruff linter, Bandit security scanner), retrieves semantically relevant repository context through a **RAG pipeline** (Qdrant vector DB + Jina AI / `nomic-embed-text` embeddings), and renders structured markdown review comments — supporting both **Hosted Cloud Mode** (Groq, Qdrant Cloud, Neon Postgres) and **Local Mode** (Ollama, Qdrant Local, Local Postgres).

Includes a **Read-Only Demo Mode** that auto-seeds pre-recorded PR review reasoning traces so recruiters and evaluators can explore the UI immediately without entering credentials.

---

## How It Works (Agentic Loop)

```
PR Diff ──► RAG Retrieval (Qdrant Cloud/Local) ──► LLM Tool-Calling Loop (Groq / Ollama)
                                                            │
                                                  ┌─────────▼─────────┐
                                                  │  Tool: Ruff Lint  │ ← LLM decides autonomously
                                                  │  Tool: Bandit     │
                                                  │  Final verdict    │
                                                  └─────────┬─────────┘
                                                            │
                                            APPROVE / COMMENT_ONLY / REQUEST_CHANGES
                                                            │
                                                  ──► GitHub PR Comment
                                                  ──► Neon / Postgres Database History
```

The LLM runs in a **multi-step tool-calling loop** (ReAct pattern): it observes the diff and RAG context, decides which static analysis tools to invoke, receives tool outputs, and iterates until it produces a structured review verdict.

---

## Features

| Feature | Details |
|---|---|
| **Hosted & Local Execution** | Switch seamlessly between **Groq API** (`LLM_PROVIDER=groq`) and **Ollama** (`LLM_PROVIDER=ollama`) |
| **Hosted Vector Embeddings** | Supports **Jina AI Embeddings** (`EMBEDDING_PROVIDER=jina`) and **Ollama** (`nomic-embed-text`) |
| **Qdrant Cloud & Neon DB** | Connection string normalization (`postgres://` -> `postgresql://`), SSL support, and Qdrant Cloud API headers |
| **Read-Only Demo Mode** | Auto-seeds 3 sample PR review traces (`demo_reviews.json`) when `DEMO_MODE=true` or when no PAT is configured |
| **Agentic Tool Calling** | LLM autonomously chooses whether to call Ruff (lint), Bandit (security), both, or neither |
| **RAG Pipeline** | AST-chunked repository indexed into Qdrant using semantic vector search |
| **Idempotency** | Two-layer guard (in-memory set + PostgreSQL unique constraint) preventing duplicate PR comments |
| **ReAct Loop Safeguard** | Iteration cap (max 5) with duplicate tool call detection and deterministic fallback verdict |
| **Single-Container Deployment** | `start.sh` launches FastAPI backend and Streamlit UI in a single container for Render / Railway |
| **CI/CD** | GitHub Actions running Ruff, Bandit security scan, and Pytest suite on every push |

---

## Tech Stack

- **Backend API**: Python 3.11+, FastAPI, Uvicorn
- **Dashboard UI**: Streamlit
- **LLM Providers**: Groq API (`qwen/qwen3.6-27b`, `llama-3.1-8b-instant`) or Local Ollama (`qwen2.5-coder:7b`)
- **Embeddings**: Jina AI Embeddings (`jina-embeddings-v2-base-en`) or Ollama (`nomic-embed-text`)
- **Vector Database**: Qdrant Cloud or Local Qdrant
- **Relational Database**: Neon Hosted PostgreSQL / Supabase or Local PostgreSQL
- **Static Analysis**: Ruff (Linting), Bandit (Security auditing)
- **Containerization & Deployment**: Docker, `start.sh`, Render Web Service

---

## Setup & Deployment

### Option A: Deploying Live to Render (Free Tier Single Web Service)

This application is packaged to run FastAPI (port 8000) and Streamlit (port 8501) inside a single Docker container via `start.sh`.

1. **Push your repository** to GitHub.
2. Log in to [Render Dashboard](https://dashboard.render.com/) and click **New +** $\rightarrow$ **Web Service**.
3. Connect your GitHub repository `rag-augmented-pr-review-agent`.
4. Select **Docker** as the Runtime environment.
5. In **Environment Variables**, add:
   - `LLM_PROVIDER`: `groq`
   - `GROQ_API_KEY`: `gsk_...`
   - `DATABASE_URL`: `postgresql://user:password@ep-xyz.neon.tech/neondb?sslmode=require`
   - `QDRANT_URL`: `https://your-cluster.aws.cloud.qdrant.io:6333`
   - `QDRANT_API_KEY`: `your_qdrant_cloud_api_key`
   - `DEMO_MODE`: `true`
6. Click **Deploy Web Service**. Render will build the Dockerfile and start the application automatically.

---

### Option B: Local Setup with Docker Compose

#### 1. Prerequisites
- Python 3.11+
- Docker Desktop
- [Ollama](https://ollama.com) (if running locally):
  ```bash
  ollama pull qwen2.5-coder:7b
  ollama pull nomic-embed-text
  ```

#### 2. Environment Configuration
Copy `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```

#### 3. Run with Docker Compose
```bash
docker compose up -d --build
```

#### 4. Run Pytest Suite
```bash
pytest tests/ -v
```

---

## Usage

### Portal UI (Streamlit Dashboard)

Access the dashboard at `http://localhost:8501` (or your live Render URL):

1. **Demo Mode**: If running in Demo Mode, pre-recorded review traces load automatically into the reasoning inspector.
2. **Connect Repository**: Enter your repository name (e.g. `owner/repo`) and your GitHub PAT.
3. **Build Knowledge Base**: Run AST repository chunking and index vectors into Qdrant.
4. **Open Pull Requests**: Inspect active pull requests fetched from GitHub.
5. **Run Review**: Click **🤖 Run Review** to trigger RAG retrieval, ReAct tool execution, and GitHub review comment posting.

---

## Environment Variables Reference

| Variable | Provider / Description |
|---|---|
| `LLM_PROVIDER` | `groq` or `ollama` (default: `groq` if `GROQ_API_KEY` present) |
| `GROQ_API_KEY` | Groq Hosted LLM API Key (`gsk_...`) |
| `GROQ_MODEL` | Groq Model ID (default: `qwen/qwen3.6-27b` or `llama-3.1-8b-instant`) |
| `EMBEDDING_PROVIDER` | `jina` or `ollama` (default: `jina` if `JINA_API_KEY` present) |
| `JINA_API_KEY` | Jina AI Hosted Embeddings API Key |
| `DATABASE_URL` | PostgreSQL connection URL (Neon / Supabase / Local) |
| `QDRANT_URL` | Qdrant Cloud Cluster URL or `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant Cloud API Key |
| `DEMO_MODE` | Set `true` to enable read-only demo fixtures |
| `DRY_RUN` | Set `true` to skip posting PR comments to GitHub during test runs |

---

## License

Distributed under the [MIT License](LICENSE).
