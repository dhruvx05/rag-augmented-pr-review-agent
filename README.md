# Autonomous PR-Review Agent

[![CI](https://github.com/your-username/pr-review-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/your-username/pr-review-agent/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org)

An autonomous pull request code-review assistant. It retrieves AST-chunked, semantically relevant repository code context via a vector-based RAG pipeline (Qdrant), executes Python static analysis and security scanning (Ruff, Bandit), prompts a locally-hosted LLM (Ollama `qwen2.5-coder:7b`), and posts formatted markdown review comments directly back to the GitHub PR. Reviews are triggered manually on-demand from a Streamlit control panel dashboard.

> **All processing is local.** No code is sent to external AI services.

---

## Features

| Feature | Details |
|---|---|
| **Manual Triggers** | Trigger reviews on-demand for any open PR directly from the Streamlit control panel UI |
| **Idempotency** | Two-layer guard (in-memory set + PostgreSQL unique constraint) preventing duplicate PR comments |
| **RAG Pipeline** | AST-chunked repository indexed into Qdrant using `nomic-embed-text` embeddings |
| **Static Analysis** | Ruff (lint) + Bandit (security) run on every changed Python file |
| **LLM Review** | Agentic tool-calling loop with deterministic fallback |
| **Database Persistence** | SQLAlchemy + PostgreSQL; structured review history schema |
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
- **Test Suite**: Pytest

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
# Edit .env and fill in your GITHUB_TOKEN (Personal Access Token)
```
*(No webhook secret is required as automatic triggering is disabled).*

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
4. **Run Review**: Click **🤖 Run Review** next to any PR. The backend FastAPI service will trigger the review pipeline, save the review record to PostgreSQL (`source='manual'`), and immediately post the markdown comment back to the GitHub PR.
5. **Reasoning Inspector**: Expand any review log to view the agentic thinking process, ruff/bandit logs, and detailed LLM prompt contents.
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

Webhook-based automatic triggering on GitHub repository events was previously implemented and fully tested. However, webhook auto-triggering has been intentionally removed in favor of manual triggers via the Streamlit dashboard. This design decision gives development teams complete control over when LLM resources are utilized and prevents duplicate webhook delivery noise on the GitHub API, while keeping the pipeline simple to operate.

---

## Developer Testing Utilities

A suite of standalone scripts for batch-testing is available in the [dev-testing/](file:///c:/Users/dhruv/Documents/AI%20project%20(PR%20review%20agent)/main/dev-testing/) folder.

- **Batch reviews**:
  ```bash
  python dev-testing/batch_review_test.py --repo "owner/repo" --prs 1 2
  ```
- **Clean up test data**:
  ```bash
  python dev-testing/cleanup_test_data.py --confirm
  ```

For more details, see [dev-testing/README.md](file:///c:/Users/dhruv/Documents/AI%20project%20(PR%20review%20agent)/main/dev-testing/README.md).
