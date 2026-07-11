# RAG-Augmented Agentic PR Review Agent

[![CI](https://github.com/dhruvx05/rag-augmented-pr-review-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/dhruvx05/rag-augmented-pr-review-agent/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

A **ReAct-pattern agentic AI** that autonomously reviews GitHub Pull Requests. The LLM decides which tools to invoke (Ruff linter, Bandit security scanner), retrieves semantically relevant repository context through a **RAG pipeline** (Qdrant vector DB + `nomic-embed-text` embeddings), and posts structured markdown review comments directly to the GitHub PR — all running locally with no data sent to external AI services.

Reviews are triggered on-demand from a Streamlit control panel dashboard.

> **All processing is local.** No code is sent to external AI services.

---

## How It Works (Agentic Loop)

```
PR Diff ──► RAG Retrieval (Qdrant) ──► LLM Reasoning Loop
                                              │
                                    ┌─────────▼─────────┐
                                    │  Tool call: Ruff?  │ ← LLM decides autonomously
                                    │  Tool call: Bandit?│
                                    │  Final verdict?    │
                                    └─────────┬─────────┘
                                              │
                              APPROVE / COMMENT_ONLY / REQUEST_CHANGES
                                              │
                                    ──► GitHub PR Comment
                                    ──► PostgreSQL History
```

The LLM runs in a **multi-step tool-calling loop** (ReAct pattern): it observes the diff and RAG context, decides which static analysis tools to invoke, receives tool results, and iterates until it produces a final structured verdict.

---

## Features

| Feature | Details |
|---|---|
| **Agentic Tool Calling** | LLM autonomously chooses whether to call Ruff (lint), Bandit (security), both, or neither |
| **RAG Pipeline** | AST-chunked repository indexed into Qdrant using `nomic-embed-text` embeddings |
| **Manual Triggers** | Trigger reviews on-demand for any open PR from the Streamlit dashboard |
| **Idempotency** | Two-layer guard (in-memory set + PostgreSQL unique constraint) preventing duplicate PR comments |
| **Static Analysis** | Ruff (lint) + Bandit (security) run dynamically on every changed Python file |
| **LLM Review** | Agentic tool-calling loop with deterministic fallback (`qwen2.5-coder:7b` via Ollama) |
| **Database Persistence** | SQLAlchemy + PostgreSQL; structured review history with soft-delete archiving |
| **Live PR Status Badges** | Real-time GitHub PR state (🟢 Merged / 🔴 Closed / 🟡 Open) in the history dashboard |
| **Analytics Dashboard** | Streamlit UI displaying code metrics and historical review verdicts |
| **Dry-Run Mode** | Full pipeline runs and logs output without posting comments to GitHub |
| **CI/CD** | GitHub Actions running Ruff, Bandit, and Pytest on every push |

---

## Tech Stack

- **Backend API**: Python, FastAPI, Uvicorn
- **Dashboard UI**: Streamlit
- **Large Language Model**: Ollama (`qwen2.5-coder:7b`)
- **Embeddings**: Ollama (`nomic-embed-text`)
- **Vector Database**: Qdrant
- **Relational Database**: PostgreSQL + SQLAlchemy
- **Static Analysis**: Ruff (Linting), Bandit (Security auditing)
- **Containerization**: Docker Compose
- **Test Suite**: Pytest (25 tests)

*No JavaScript or TypeScript is used in this repository.*

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
