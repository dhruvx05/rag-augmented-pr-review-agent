# Architecture

Detailed design reference for the Autonomous PR-Review Agent v1.0.

---

## Component Overview

| Component | File | Responsibility |
|---|---|---|
| **API Server** | `pr-review-agent/app.py` | Receives on-demand trigger events, coordinates background reviews |
| **Review Agent** | `pr-review-agent/agent.py` | LLM agentic loop, RAG retrieval, fallback pipeline, verdict parsing |
| **Tool Executors** | `pr-review-agent/tools.py` | Fetches file content from GitHub; runs Ruff and Bandit |
| **GitHub Client** | `pr-review-agent/github_client.py` | Fetches PR diff, head SHA, and posts review comments |
| **Database** | `pr-review-agent/database.py` + `models.py` | SQLAlchemy session management and Review schema |
| **Repository Indexer** | `index_repo.py` | Walks a repo, AST-chunks Python files, uploads embeddings to Qdrant |
| **Analytics Dashboard** | `dashboard.py` | Streamlit UI that queries FastAPI `/reviews` |

---

## Request Flow

Reviews are triggered manually on-demand from the Streamlit dashboard:

```
Streamlit Dashboard
        │
        ▼ (User clicks "Run Review")
POST /config/trigger-review (FastAPI)
        │
        ├─► Idempotency check
        │         DB: query Reviews by (repo, pr_number, commit_sha)
        │         Memory: check _in_progress_commits set
        │         (Abort if already processed)
        │
        └─► BackgroundTask: process_pr_review()
                    │
                    ├─► configure_tools()    — set repo/token/SHA context
                    ├─► fetch_pr_diff()      — GitHub API → list of patches
                    ├─► retrieve_related_context()  — Qdrant vector search
                    ├─► run_lint() / run_security_scan() — Ruff + Bandit
                    ├─► review_pr()          — Ollama LLM verdict
                    ├─► INSERT Review        — PostgreSQL (idempotency lock, source='manual')
                    └─► post_pr_comment()    — GitHub PR comment (posted automatically)
```

---

## Database Schema

```sql
CREATE TABLE reviews (
    id          SERIAL PRIMARY KEY,
    repo        VARCHAR NOT NULL,
    pr_number   INTEGER NOT NULL,
    commit_sha  VARCHAR NOT NULL,
    decision    VARCHAR NOT NULL,   -- APPROVE | COMMENT_ONLY | REQUEST_CHANGES
    summary     TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    relevance   TEXT,
    source      VARCHAR DEFAULT 'webhook',
    created_at  TIMESTAMP DEFAULT now(),

    UNIQUE (repo, pr_number, commit_sha)  -- idempotency constraint
);
```

The unique constraint on `(repo, pr_number, commit_sha)` is the durable idempotency lock. If a concurrent worker races and inserts first, the second worker gets an `IntegrityError`, rolls back, and aborts before posting a duplicate comment.

---

## Idempotency Design

The agent uses two complementary guards:

**Layer 1 — In-memory set** (`_in_progress_commits`)
- Prevents two background tasks from starting for the same commit simultaneously.
- Fast check, no DB round-trip.
- Limitation: lost on process restart.

**Layer 2 — Database unique constraint**
- Prevents a review from being inserted twice even across restarts or race conditions.
- The INSERT happens *before* the GitHub comment is posted, so a failure after insert but before comment is recoverable (manual re-trigger).

---

## RAG Pipeline

### Indexing phase (`index_repo.py`)

1. Walk the repository, filtering out `.git`, `venv`, `__pycache__`.
2. For each Python file: parse with `ast.NodeVisitor`, extract every `FunctionDef` and `ClassDef` as a discrete chunk.
3. For files with no class/function definitions (or non-Python files): treat the entire file as one chunk.
4. For each chunk: call `nomic-embed-text` via Ollama to generate a 768-dimensional vector.
5. Upsert vectors into Qdrant with metadata payload: `file_path`, `function_name`, `start_line`, `end_line`, `content`, `repo`.

### Retrieval phase (`agent.py → retrieve_related_context`)

1. Extract added lines (`+` prefix) from the PR diff to form a focused query string.
2. Embed the query string with `nomic-embed-text`.
3. Search Qdrant with a repository filter to return the top-k most similar chunks.
4. Cap combined context at `RAG_CONTEXT_CHAR_BUDGET` (4,000 characters) to prevent token overflow.

---

## LLM Review Loop

### Agentic mode (default)

The model receives the diff and optional RAG context. It decides autonomously whether to call:
- `run_lint(file_path)` — fetch file from GitHub and run Ruff via stdin.
- `run_security_scan(file_path)` — fetch file from GitHub, write to temp file, run Bandit.

The loop iterates up to 6 times. When the model stops issuing tool calls, its response is parsed as the final verdict.

### Fallback mode (`--no-tools` or on agentic failure)

Ruff and Bandit run deterministically on every changed `.py` file, then all outputs are bundled into one prompt. Ollama's `format: json` mode is enabled to maximise parse reliability.

### Verdict parsing

`parse_and_validate_verdict` strips markdown fences and validates four required keys:
- `decision` ∈ `{APPROVE, COMMENT_ONLY, REQUEST_CHANGES}`
- `reason` (string)
- `summary` (string)
- `security_flags` (list)

On validation failure it retries once by sending the schema back to the model with `format: json`.

---

## Static Analysis Tools

Both tools share a common pattern:
1. Validate that the file is a `.py` file and tool context is configured.
2. Fetch the file at the exact `head_sha` from GitHub Contents API.
3. Run the tool, replacing temp file paths with the real path in output.
4. Return a clean report string to the LLM agent.

Subprocess fallback: if the tool binary is not on `PATH`, re-run via `sys.executable -m <tool>` to ensure the virtualenv version is used.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Local LLM only | No code leaves the machine; no API costs; works offline |
| AST chunking over line-based chunking | Produces semantically meaningful units; avoids splitting functions mid-body |
| Background task over async processing | Ollama LLM queries can take significant time; on-demand reviews run asynchronously |
| DB insert before comment post | Makes the insert the atomic idempotency lock; comment failure is retryable |
| Fallback pipeline | `qwen2.5-coder:7b` tool-calling is occasionally unreliable; fallback ensures reviews always complete |
| `sys.executable` for subprocesses | Ensures tools run inside the correct virtualenv regardless of PATH |
| Webhook triggering removed | Deliberately removed in favor of manual dashboard reviews for simpler operation and more control. See [walkthrough.md](../walkthrough.md) for the historical record of webhook implementations. |
