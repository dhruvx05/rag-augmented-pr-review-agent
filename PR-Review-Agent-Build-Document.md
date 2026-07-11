# Autonomous PR Review Agent — Build Document

A working reference for building this project in stages, from a functional prototype today to a full agentic pipeline with RAG. Each iteration is a complete, runnable, demoable state — not a partial build. Only claim on your resume what's actually done at the iteration you've reached.

---

## 0. Project Summary

An agent that reviews GitHub pull requests without being asked. It fetches a PR's diff, reasons over it using a local LLM, decides for itself which tools to call (lint, retrieve similar code, security scan) before committing to a verdict, and returns a decision: `APPROVE`, `COMMENT_ONLY`, or `REQUEST_CHANGES`, with a reason.

The core idea that makes this "agentic" and not just "call an LLM once": the model controls its own next action. You don't hardcode "always lint then always answer" — the model decides, per PR, what information it needs.

---

## 1. Requirements

### Software
- Python 3.11+
- Ollama (local LLM runtime) — [ollama.com](https://ollama.com)
- Git + a GitHub account with a Personal Access Token (`repo` scope)
- `ruff` (Python linter)
- Docker + Docker Compose (from Iteration 2 onward)
- Google Antigravity or another AI coding tool (optional, for scaffolding)

### Hardware
- At least 8GB RAM (16GB+ recommended if you want to run `deepseek-coder-v2:16b` instead of the 7B model)
- ~10GB free disk for Ollama models + Docker images (once you add those)

### Accounts / Access
- A GitHub repo you control, to use as your test target (a dummy repo is fine and recommended)
- GitHub PAT with `repo` scope for API access

---

## 2. Full Tech Stack (introduced progressively — see iteration table)

| Layer | Tool | Introduced in | Why |
|---|---|---|---|
| LLM | Ollama + `qwen2.5-coder:7b` | Iteration 0 | Free, local, no API key, coding-tuned, decent structured output |
| Diff source | GitHub REST API + PAT | Iteration 0 | Standard, no OAuth complexity |
| Lint tool | `ruff` | Iteration 0 | One-command Python linter, fast |
| Testing | Custom regression script | Iteration 0 | Known-outcome PRs to catch regressions as you tune the prompt |
| Web framework | FastAPI | Iteration 1 | Async-native, handles webhooks + LLM calls well |
| Trigger | GitHub Webhook + `ngrok` | Iteration 1 | Turns it from "a script I run" into "a bot that watches a repo" |
| Comment posting | GitHub REST API (create comment) | Iteration 1 | Closes the loop — agent posts its own review |
| Containerization | Docker + Docker Compose | Iteration 2 | Reproducible setup, one command to run everything |
| Persistence | Postgres (or SQLite if you want to stay light) | Iteration 2 | Stores review history, avoids duplicate processing |
| Embeddings | `nomic-embed-text` (via Ollama) or `bge-small-en-v1.5` (via `sentence-transformers`) | Iteration 3 | Turns code into vectors for similarity search |
| Vector DB | Qdrant (Docker) | Iteration 3 | Stores embedded codebase, enables RAG retrieval tool |
| Security scan | `bandit` | Iteration 4 | Adds a distinct tool the agent can call |
| CI | GitHub Actions | Iteration 4 | Lint/test/build on every push |
| Formal testing | `pytest` with mocked LLM/API calls | Iteration 4 | Proper unit tests once code surface area grows |

You will not use everything in this table today. Iteration 0 uses only the first three rows.

---

## 3. Full Architecture (end state — what you're building *toward*)

```
GitHub PR opened/updated
        │
        ▼
GitHub Webhook ──POST──▶ FastAPI /webhook
                                │
                                ▼
                       Agent Orchestrator (loop)
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              Tool: Lint   Tool: RAG    Tool: Security
              (ruff)       (Qdrant)     (bandit)
                    │           │           │
                    └─────┬─────┴─────┬─────┘
                          ▼           
                  Ollama (qwen2.5-coder:7b)
                          │ verdict JSON
                          ▼
                  GitHub API (post comment)

Supporting infra: Postgres (history), Qdrant (vectors), ngrok (tunnel for demo)
```

At Iteration 0 (today), this collapses to just: **you run a script → diff fetch → agent loop with one tool (lint) → verdict printed to terminal.** No webhook, no Docker, no DB, no RAG yet.

---

## 4. Iteration Plan

### Iteration 0 — Core Agent Loop (TODAY)

**Goal:** A runnable script that proves the agentic loop works end to end.

**Requirements:** Ollama running locally, `ruff` installed, a GitHub PAT, one test PR (real or dummy).

**Repo structure:**
```
pr-review-agent/
├── github_client.py   # fetch_pr_diff()
├── tools.py           # run_lint()
├── agent.py           # review_pr() — the loop itself
├── main.py            # CLI entrypoint
├── run_test_set.py    # regression script
├── requirements.txt
└── README.md
```

**Functional flow:**
```
python main.py --repo you/your-repo --pr 1 --token YOUR_TOKEN
  1. fetch_pr_diff() calls GitHub API, returns [{file_path, patch_text}, ...]
  2. review_pr(diff) sends diff to Ollama
  3. Model decides: does this diff need linting? If yes → calls run_lint(file_path)
  4. Lint result fed back to the model
  5. Model returns JSON: {decision, reason, summary}
  6. main.py prints the verdict
```

**Key design note:** Ollama tool-calling on a 7B model can be unreliable. If the model won't call tools cleanly, use a two-step fallback: always run lint first, feed the diff + lint result together in one prompt, get the JSON verdict back. This is a legitimate, explainable design choice — say so directly if asked, don't pretend it's true agentic tool-calling if you had to fall back.

**Testing (see full detail in Section 5):**
- Test each function in isolation first (`fetch_pr_diff`, `run_lint`, raw Ollama call).
- Then test the full flow against a dummy PR with a known issue.
- Build `run_test_set.py` — 3-4 PRs with known expected verdicts, run automatically, print pass/fail.

**Definition of done:** Script runs against a real PR, returns a coherent verdict, and you can explain every line of `agent.py` without hesitation.

**Resume claim at this stage:**
> "Building an autonomous PR-review agent using a local LLM (Ollama) in a tool-calling loop — the model decides whether to run static analysis before returning a structured review verdict."

---

### Iteration 1 — Webhook + Auto-Posting (Week 1)

**Goal:** Turn the manual script into an always-on bot.

**Adds:** FastAPI, `ngrok`, GitHub webhook registration, comment-posting.

**New repo structure additions:**
```
├── main.py             # now a FastAPI app, not a CLI
├── webhook.py           # receives + verifies GitHub webhook signature (HMAC-SHA256)
├── github_client.py      # add post_review_comment()
```

**Functional flow:**
```
1. Developer opens/updates a PR on GitHub
2. GitHub sends a webhook POST to /webhook (HMAC signature verified)
3. FastAPI parses payload, extracts {repo, pr_number}
4. Same Iteration 0 logic runs: fetch diff → agent loop → verdict
5. If decision requires a comment, post_review_comment() posts it via GitHub API
6. Developer sees the comment on their actual PR
```

**Debugging notes:**
- Verify the webhook signature correctly — GitHub sends an `X-Hub-Signature-256` header; compute HMAC-SHA256 with your webhook secret and compare.
- `ngrok` URLs change on restart — you'll need to re-register the webhook each session, or note this as a known limitation.
- Don't process the same commit twice — check before running if `{repo, pr_number, commit_sha}` was already reviewed (in-memory set is fine for now, DB comes in Iteration 2).

**Definition of done:** Open a real PR on GitHub, watch the agent's comment appear automatically without you running anything manually.

**Resume claim upgrade:**
> "...watches GitHub pull requests via webhook and posts its review directly on the PR."

---

### Iteration 2 — Containerization + Persistence (Week 1-2)

**Goal:** Reproducible setup, avoid duplicate processing, store history.

**Adds:** Docker, Docker Compose, Postgres (or SQLite if you want to stay lighter).

**New repo structure additions:**
```
├── docker-compose.yml
├── Dockerfile
├── db/
│   ├── models.py       # review history table
│   └── session.py
```

**Functional flow addition:**
```
Before running the agent loop: check DB — already reviewed this commit? Skip if so.
After the verdict: save {pr_number, decision, reason, latency, timestamp} to DB.
```

**Debugging notes:**
- Use `depends_on` + healthchecks in Compose so FastAPI doesn't start before Postgres is ready.
- Test the full container stack with a clean `docker-compose up` on a fresh clone — this is what "reproducible" actually means, verify it, don't assume it.

**Definition of done:** `docker-compose up` on a clean machine gets the whole stack running with one command.

---

### Iteration 3 — RAG Retrieval (Week 2 — your AIML differentiator)

**Goal:** Give the agent a second tool: retrieving similar code from the existing codebase to inform its review.

**Adds:** Embeddings model, Qdrant, an ingestion pipeline.

**New repo structure additions:**
```
├── ingestion/
│   └── embed_repo.py    # chunks + embeds a repo into Qdrant
├── tools.py              # add retrieve_similar_code()
```

**Functional flow addition:**
```
1. One-time (or on-connect) step: walk the repo, parse each file with Python's
   ast module, chunk by function/class, embed each chunk, upsert into Qdrant
   with metadata {file_path, name, start_line, end_line}
2. In the agent loop, the model can now call retrieve_similar_code(query, top_k)
   — embeds the query, searches Qdrant, returns top matches
3. Model uses this context (e.g. "how does this codebase usually handle errors?")
   alongside lint results before returning its verdict
```

**Debugging notes:**
- Chunk by function/class, not fixed-size text blocks — preserves semantic meaning, and it's a good interview answer for "why did you chunk this way."
- Re-embedding a large repo can be slow — for a demo, keep the test repo small (a few dozen files).
- Verify retrieval quality manually before trusting it in the loop — search for a known function and confirm it comes back as a top match.

**Definition of done:** Ask the agent to review a PR that touches error-handling logic, and confirm it actually retrieves and references genuinely similar code from elsewhere in the repo — not just a random function.

**Resume claim upgrade:**
> "...retrieves similar code from the existing codebase via RAG (Qdrant) to inform its review, alongside static analysis."

---

### Iteration 4 — Polish (only if time allows, in priority order)

1. **Security scan tool (`bandit`)** — second static-analysis tool, cheap to add once the pattern from `run_lint` exists.
2. **Automated regression suite formalized with `pytest`** — mock the LLM and GitHub calls, test `run_lint`, test JSON verdict parsing including malformed output.
3. **Dry-run mode** — one env var (`AUTO_POST=true|false`), lets you test without spamming a real repo. Very cheap, good safety talking point.
4. **README polish** — architecture diagram, setup instructions that actually work on a clean clone, honest "known limitations" section.
5. **Dashboard** — only if you have real spare time; a simple read-only page showing review history is a "nice to have," not core to the story. Do not attempt this in the same day as core functionality.
6. **Formal eval (precision/recall on a labeled test set)** — genuinely impressive but needs real labeled data you build yourself; don't fake numbers, and don't claim this exists until you've actually run it.

---

## 5. Testing & Debugging Guide (applies across iterations)

### Manual testing, in order
1. Test each function in isolation before testing the full pipeline (`fetch_pr_diff` alone, `run_lint` alone, a raw Ollama call alone).
2. Confirm Ollama responds at all, outside your code: `ollama run qwen2.5-coder:7b "say hello"`.
3. Run the full flow against a dummy PR with one deliberate, known issue (e.g. an unused import).
4. Confirm the JSON verdict parses correctly and the `reason` references something real in the diff — not a hallucinated file or issue.

### Automated regression testing
Build a small set of PRs with known expected outcomes (2 clean, 2 with planted issues). Script that runs the real pipeline against all of them and reports pass/fail:

```python
# run_test_set.py
TEST_CASES = [
    {"pr": 1, "repo": "you/test-repo", "expected": "REQUEST_CHANGES"},
    {"pr": 2, "repo": "you/test-repo", "expected": "APPROVE"},
]
# loop, compare actual vs expected, print summary, save to test_results.json
```
Rerun this every time you change the prompt or logic — it's your regression net. Call this "an automated regression script with known-outcome test PRs," not "precision/recall on a golden test set" unless you've actually built a real labeled set (Iteration 4, item 6).

### Deliberately test failure modes (this is what makes it defensible in interviews)
- PR with no issues → does it correctly say `APPROVE`, or does it always flag something?
- Wrong/expired PAT → fails gracefully, or crashes ugly?
- Huge diff → does it choke on token limits? (Mitigate: truncate diff text past ~4000 characters with a note appended.)
- Malformed JSON from the model → have a retry or fallback, don't assume it never happens.

### Common failure points by iteration
| Issue | Likely cause | Fix |
|---|---|---|
| Ollama tool-calling not triggering | 7B models are inconsistent at function-calling | Use the two-step fallback (always lint, feed result in one prompt) |
| Webhook never received | `ngrok` URL changed, GitHub still pointing at old one | Re-register webhook each session, or note as known limitation |
| Duplicate comments on same PR | No idempotency check | Check `{repo, pr, commit_sha}` before processing |
| Qdrant returns irrelevant matches | Poor chunking or wrong embedding model at query time | Chunk by function, ensure ingestion + query use the same embedding model |
| Docker Compose fails on fresh clone | Missing healthcheck/depends_on ordering | Add healthchecks, test on an actual clean clone before trusting it |

---

## 6. What Not to Claim Until It's True

- Don't say "posts comments automatically" until Iteration 1 is done and tested live.
- Don't say "containerized" until `docker-compose up` genuinely works on a clean clone.
- Don't say "uses RAG" until Iteration 3 is built and you've manually verified retrieval quality.
- Don't cite precision/recall numbers unless you've built and run a real labeled test set — a small pass/fail regression script is fine to mention, but call it what it is.
- If you used an AI coding tool (Antigravity) to scaffold parts of it, say so plainly if asked — normal practice, just be able to explain the logic yourself, especially the agent loop.

---

## 7. Interview-Ready Questions to Have Answers For (grows with each iteration)

- Walk me through what happens end-to-end when a PR is opened.
- Why did you choose a local model over a hosted API?
- How does the agent decide whether to call a tool versus answer directly?
- What happens if the LLM returns malformed JSON?
- Why did you chunk code by function instead of fixed-size blocks? (Iteration 3+)
- How would this scale to a large repo with thousands of files? (Answer: incremental embedding on commit, not full re-embed.)
- What are the current limitations, and what would you add next?

Answer these honestly based on whichever iteration you've actually reached — "I haven't built X yet, here's how I'd approach it" is a completely acceptable answer and often lands better than a vague or overstated one.
