# RAG-Augmented Agentic PR Review Agent

[![CI](https://github.com/dhruvx05/rag-augmented-pr-review-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dhruvx05/rag-augmented-pr-review-agent/actions)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/dhruvx05/rag-augmented-pr-review-agent)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

A **ReAct-pattern agentic AI** that autonomously reviews GitHub Pull Requests. The LLM decides which tools to invoke (Ruff linter, Bandit security scanner), retrieves semantically relevant repository context through a **RAG pipeline** (Qdrant vector DB + Jina AI / `nomic-embed-text` embeddings), and renders structured markdown review comments — supporting both **Hosted Cloud Mode** (Groq API, Qdrant Cloud, Neon Postgres) and **Local Mode** (Ollama, Qdrant Local, Local Postgres).

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
| **Single-Container Deployment** | `start.sh` launches FastAPI backend (8000) and Streamlit UI (8501) in a single container |
| **Render Web Service Ready** | Includes `render.yaml` blueprint for 1-click cloud deployment on Render free tier |
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
---

## Setup

### Prerequisites

- Python 3.11+
- Docker Desktop
- [Ollama](https://ollama.com) with models pulled:
  ```bash
  ollama pull qwen2.5-coder:7b
  ollama pull nomic-embed-text
  ```

### 1. Install dependencies

```bash
python -m venv pr-review-agent/venv
# Windows
.\pr-review-agent\venv\Scripts\activate
# macOS / Linux
source pr-review-agent/venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your GITHUB_TOKEN (Personal Access Token with repo scope)
```

### 3. Start the infrastructure

```bash
docker compose up -d --build
```
This starts PostgreSQL, Qdrant, and the FastAPI backend server.

### 4. Index your repository (RAG setup)

Run this once to parse, embed, and index your target repository into Qdrant:

```bash
python index_repo.py --repo-path /path/to/your/repo --repo-name owner/repo
```

---

## Usage

### Portal UI (Dashboard)

Start the dashboard using Streamlit:

```bash
streamlit run dashboard.py
```

Then open `http://localhost:8501` to:
1. **Connect Repository**: Enter your repository name (e.g. `owner/repo`) and your GitHub PAT.
2. **Index Repository**: Confirm that Qdrant contains your repository index (or trigger a rebuild index background task).
3. **View Pull Requests**: Inspect a list of all open pull requests fetched live from GitHub.
4. **Run Review**: Click **🤖 Run Review** next to any PR. The agentic pipeline fetches the diff, runs RAG retrieval, enters the LLM tool-calling loop, and posts the review comment to GitHub.
5. **Reasoning Inspector**: Expand any review log to view the agentic thinking process, ruff/bandit outputs, and detailed LLM reasoning.
6. **Analytics**: Inspect total reviews, approval rates, and decision distribution.

### CLI (single review)

You can also run a review on a single PR directly from the command line:

```bash
cd pr-review-agent
python main.py --repo owner/repo --pr 42 --token ghp_...
```

---

## Environment Variables

| Variable | Required | Description |
|---|:---:|---|
| `GITHUB_TOKEN` | ✅ | Default GitHub PAT with `repo` scope (for fallback CLI tests) |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `OLLAMA_HOST` | ✅ | Ollama endpoint (default: `http://localhost:11434`) |
| `QDRANT_URL` | ✅ | Qdrant endpoint (default: `http://localhost:6333`) |
| `DRY_RUN` | | Set `true` to skip posting GitHub comments during pipeline runs |
| `API_URL` | | FastAPI base URL for the dashboard (default: `http://localhost:8000`) |

---

## Design Decisions

**Manual triggers over webhooks**: Webhook-based automatic triggering was previously implemented and fully tested. It has been intentionally removed in favor of on-demand manual triggers via the Streamlit dashboard. This gives complete control over when LLM resources are consumed and keeps the pipeline straightforward to operate.

**Agentic over scripted**: Rather than always running Ruff and Bandit unconditionally, the LLM decides whether static analysis is necessary based on the diff content and RAG context. This mirrors how a senior engineer would triage a PR before diving into tool-assisted review.

---

## Developer Testing Utilities

A suite of standalone scripts for batch-testing is available in the `dev-testing/` folder.

- **Batch reviews**:
  ```bash
  python dev-testing/batch_review_test.py --repo "owner/repo" --prs 1 2
  ```
- **Clean up test data**:
  ```bash
  python dev-testing/cleanup_test_data.py --confirm
  ```
