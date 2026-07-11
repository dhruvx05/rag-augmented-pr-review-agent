import os
import sys
import logging
import datetime as _dt
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("pr-review-agent")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() == "true"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")


# In-memory set tracking commits currently under review.
# Prevents concurrent duplicate reviews for the same commit.
# NOTE: Does not survive process restarts; the DB unique constraint
# provides the durable idempotency guarantee.
_in_progress_commits: set = set()

# Active connection state (stored in backend memory)
_active_repo: str = ""
_active_token: str = ""
_active_status: str = "disconnected"

_indexing_state: dict = {
    "status": "idle",  # "idle", "cloning", "indexing", "completed", "failed"
    "repo": "",
    "chunks_count": 0,
    "error": None
}

# Timestamp bumped every time a review is persisted.
# The dashboard polls /status and only reruns when this changes.
_last_review_at: str = ""




@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup: verify database connection and schema."""
    logger.info("Starting PR-Review Agent service...")

    if DRY_RUN:
        logger.warning(
            "\n" + "*" * 60 + "\n"
            "* WARNING: DRY-RUN MODE IS ACTIVE                          *\n"
            "* Comments will NOT be posted to GitHub!                   *\n"
            + "*" * 60 + "\n"
        )

    if not GITHUB_TOKEN:
        logger.error("GITHUB_TOKEN is not set — review comment posting will fail.")

    from database import engine, Base
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as exc:
        logger.critical(f"Database connection failed: {exc}")
        sys.exit(1)

    try:
        import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        
        # Safe migration for relevance and source columns
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(engine)
            columns = [c["name"] for c in inspector.get_columns("reviews")]
            if "relevance" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN relevance TEXT"))
                logger.info("Database migration: Added 'relevance' column to 'reviews' table.")
            if "source" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN source TEXT DEFAULT 'webhook'"))
                logger.info("Database migration: Added 'source' column to 'reviews' table.")
            if "archived" not in columns:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN archived BOOLEAN DEFAULT FALSE"))
                logger.info("Database migration: Added 'archived' column to 'reviews' table.")
            
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_decision ON reviews(decision)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_archived ON reviews(archived)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reviews_created_at ON reviews(created_at)"))
                logger.info("Database migration: Verified and created indexes on filtering columns.")
            except Exception as index_exc:
                logger.warning(f"Database migration indexes check/run warning: {index_exc}")
        except Exception as migration_exc:
            logger.warning(f"Database migration check/run warning: {migration_exc}")

        logger.info("Database schema ready.")
        logger.info("READY: PR-Review Agent backend service live")
    except Exception as exc:
        logger.critical(f"Database schema initialization failed: {exc}")
        sys.exit(1)

    yield


app = FastAPI(
    title="PR Review Agent",
    description="Autonomous code review agent.",
    version="1.0.0",
    lifespan=lifespan,
)


def _build_comment(verdict: dict, pr_number: int) -> str:
    """Formats the LLM verdict as a GitHub PR comment in Markdown."""
    decision = verdict.get("decision", "COMMENT_ONLY")
    summary = verdict.get("summary", "No summary provided.")
    reason = verdict.get("reason", "No details provided.")
    relevance = verdict.get("relevance", "✅ Relevant")

    body = (
        f"### 🤖 PR Review Verdict: **{decision}**\n\n"
        f"**PR Relevance**: {relevance}\n\n"
        f"**Summary**: {summary}\n\n"
        f"**Reasoning**: {reason}\n\n"
    )

    if verdict.get("security_flags"):
        body += "**Security Issues Found**:\n"
        for flag in verdict["security_flags"]:
            body += (
                f"- **{flag.get('severity')}** in `{flag.get('file')}` "
                f"(line {flag.get('line')}): {flag.get('issue')}\n"
            )
        body += "\n"

    body += "---\n*Reviewed autonomously by `qwen2.5-coder:7b` via PR Review Agent.*"
    return body


def process_pr_review(repo: str, pr_number: int, commit_sha: str, token: str, source: str = "manual") -> None:
    """
    Background worker that fetches, analyses, and posts a review for a single PR commit.

    Steps:
        1. Check DB for an existing review (second idempotency guard).
        2. Configure tool context (token, repo, SHA).
        3. Fetch the PR diff from GitHub.
        4. Run the LLM review agent.
        5. Persist the verdict to PostgreSQL.
        6. Post the verdict as a GitHub PR comment (or log in dry-run mode).
    """
    logger.info(f"Review started: {repo} PR #{pr_number} @ {commit_sha}")
    idempotency_key = (repo, pr_number, commit_sha)

    from database import SessionLocal
    from models import Review
    from sqlalchemy.exc import IntegrityError

    db = SessionLocal()
    try:
        # Guard against a race where another worker finished while this one was queued.
        if db.query(Review).filter_by(repo=repo, pr_number=pr_number, commit_sha=commit_sha).first():
            logger.info(f"Already reviewed in DB: {commit_sha}. Skipping.")
            return

        from tools import configure_tools
        configure_tools(repo=repo, token=token, pr_number=pr_number, head_sha=commit_sha)

        from github_client import fetch_pr_diff
        diff_files = fetch_pr_diff(repo, pr_number, token)

        if not diff_files:
            logger.info(f"PR #{pr_number} has an empty diff. Recording APPROVE and skipping.")
            try:
                db.add(Review(
                    repo=repo, pr_number=pr_number, commit_sha=commit_sha,
                    decision="APPROVE", reason="Empty diff — no reviewable code.", summary="Empty diff",
                    relevance="✅ Relevant", source=source,
                ))
                db.commit()
            except IntegrityError:
                db.rollback()
            return

        from agent import review_pr
        logger.info("Running LLM review agent...")
        verdict = review_pr(diff_files, use_tool_calling=True, repo=repo, token=token)

        try:
            db.add(Review(
                repo=repo, pr_number=pr_number, commit_sha=commit_sha,
                decision=verdict.get("decision", "COMMENT_ONLY"),
                reason=verdict.get("reason", ""),
                summary=verdict.get("summary", ""),
                relevance=verdict.get("relevance", "✅ Relevant"),
                source=source,
            ))
            db.commit()
            logger.info("Review verdict persisted to database.")
            # Bump the change-detection timestamp so the dashboard knows to refresh
            global _last_review_at
            _last_review_at = _dt.datetime.utcnow().isoformat() + "Z"
        except IntegrityError:
            db.rollback()
            logger.warning(f"Concurrent write detected for {commit_sha}. Aborting to avoid duplicate comment.")
            return

        comment = _build_comment(verdict, pr_number)

        if DRY_RUN:
            logger.warning(f"[DRY-RUN] Would post to {repo} PR #{pr_number}:\n{comment}")
        else:
            from github_client import post_pr_comment
            post_pr_comment(repo, pr_number, comment, token)
            logger.info(f"Review comment posted to {repo} PR #{pr_number}.")

        logger.info(f"Review complete: {repo} PR #{pr_number} → {verdict.get('decision')}")

    except Exception as exc:
        logger.error(
            f"Review failed for {repo} PR #{pr_number} @ {commit_sha}: {exc}",
            exc_info=True,
        )
    finally:
        _in_progress_commits.discard(idempotency_key)
        db.close()




@app.get("/health")
def health_check():
    """Returns service liveness status and basic configuration state."""
    from database import SessionLocal
    from models import Review

    db_ok = True
    review_count = 0
    try:
        db = SessionLocal()
        review_count = db.query(Review).count()
        db.close()
    except Exception as exc:
        logger.error(f"Health check DB error: {exc}")
        db_ok = False

    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database_connected": db_ok,
        "token_configured": bool(GITHUB_TOKEN),
        "dry_run": DRY_RUN,
        "total_reviews": review_count,
    }


@app.get("/reviews/in-progress")
def get_in_progress_reviews():
    """Returns a list of reviews currently executing in the background."""
    return [
        {"repo": r, "pr_number": p, "commit_sha": c}
        for (r, p, c) in _in_progress_commits
    ]


@app.get("/status")
def get_status():
    """
    Lightweight change-detection endpoint for the dashboard.
    Returns the timestamp of the last completed review.
    The dashboard compares this against its cached value and only
    triggers a full page refresh when the value changes.
    """
    return {
        "last_review_at": _last_review_at,
        "in_progress": len(_in_progress_commits) > 0,
    }


@app.get("/reviews")
def get_reviews(repo: str | None = None, decision: str | None = None, include_archived: bool = False):
    """
    Returns a list of past review records from the database.

    Query parameters:
        repo:     Filter by repository full name (e.g. ``owner/repo``).
        decision: Filter by verdict (``APPROVE``, ``COMMENT_ONLY``, ``REQUEST_CHANGES``).
        include_archived: Include soft-deleted/archived reviews.
    """
    from database import SessionLocal
    from models import Review
    from sqlalchemy import or_

    db = SessionLocal()
    try:
        query = db.query(Review)
        if repo:
            query = query.filter(Review.repo == repo)
        if decision:
            query = query.filter(Review.decision == decision)
        if not include_archived:
            query = query.filter(or_(Review.archived.is_(False), Review.archived.is_(None)))

        reviews = query.order_by(Review.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "repo": r.repo,
                "pr_number": r.pr_number,
                "commit_sha": r.commit_sha,
                "decision": r.decision,
                "summary": r.summary,
                "reason": r.reason,
                "relevance": r.relevance if r.relevance else "✅ Relevant",
                "source": r.source if r.source else "webhook",
                "archived": r.archived if r.archived is not None else False,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reviews
        ]
    except Exception as exc:
        logger.error(f"Failed to query reviews: {exc}")
        raise HTTPException(status_code=500, detail="Database query failed.")
    finally:
        db.close()


class ArchiveReviewsRequest(BaseModel):
    ids: list[int]


@app.post("/reviews/archive")
def archive_reviews(req: ArchiveReviewsRequest):
    """Soft-deletes/archives the specified reviews by setting archived=True."""
    from database import SessionLocal
    from models import Review
    db = SessionLocal()
    try:
        db.query(Review).filter(Review.id.in_(req.ids)).update({"archived": True}, synchronize_session=False)
        db.commit()
        return {"status": "success", "archived_count": len(req.ids)}
    except Exception as exc:
        db.rollback()
        logger.error(f"Failed to archive reviews: {exc}")
        raise HTTPException(status_code=500, detail="Database update failed.")
    finally:
        db.close()



class TriggerRequest(BaseModel):
    repo: str
    pr_number: int
    token: str


@app.post("/trigger")
def trigger_review(req: TriggerRequest, background_tasks: BackgroundTasks):
    """
    Triggers a review for a specific PR on-demand.
    """
    from github_client import get_pr_head_sha
    try:
        commit_sha = get_pr_head_sha(req.repo, req.pr_number, req.token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch PR branch metadata: {exc}")

    # Check database and in-progress sets for idempotency
    idempotency_key = (req.repo, req.pr_number, commit_sha)

    from database import SessionLocal
    from models import Review
    db = SessionLocal()
    try:
        if db.query(Review).filter_by(repo=req.repo, pr_number=req.pr_number, commit_sha=commit_sha).first():
            return {"status": "already_reviewed", "message": "Already reviewed."}
    finally:
        db.close()

    if idempotency_key in _in_progress_commits:
        return {"status": "in_progress", "message": "Review already in progress."}

    _in_progress_commits.add(idempotency_key)
    background_tasks.add_task(
        process_pr_review,
        repo=req.repo,
        pr_number=req.pr_number,
        commit_sha=commit_sha,
        token=req.token,
        source="manual",
    )

    return {"status": "queued", "message": "Review queued in background."}


# ---------------------------------------------------------------------------
# SaaS Config and Automation APIs
# ---------------------------------------------------------------------------

class ConfigSaveRequest(BaseModel):
    repo: str
    token: str



class TriggerReviewRequest(BaseModel):
    pr_number: int


def _check_qdrant_indexed_chunks(repo: str) -> int:
    """Queries Qdrant points count for the given repository."""
    import requests
    try:
        url = f"{QDRANT_URL}/collections/pr_reviews/points/count"
        payload = {
            "filter": {
                "must": [
                    {"key": "repo", "match": {"value": repo}}
                ]
            }
        }
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("count", 0)
    except requests.RequestException as exc:
        logger.warning(f"Qdrant chunk count unavailable for '{repo}': {exc}")
    return 0


def _run_background_indexing(repo: str, token: str):
    """Clones and runs repository AST indexer in the background."""
    global _indexing_state
    _indexing_state["status"] = "cloning"
    _indexing_state["repo"] = repo
    _indexing_state["error"] = None
    _indexing_state["chunks_count"] = 0

    import tempfile
    import shutil
    import subprocess
    import uuid

    # Create a temp dir inside system temp path
    temp_dir = tempfile.gettempdir()
    clone_path = os.path.join(temp_dir, f"clone_{uuid.uuid4().hex[:8]}")
    auth_url = f"https://x-access-token:{token}@github.com/{repo}.git"

    try:
        logger.info(f"Background Indexing: cloning {repo}...")
        res = subprocess.run(["git", "clone", "--depth", "1", auth_url, clone_path], capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError(f"Git clone failed: {res.stderr}")

        _indexing_state["status"] = "indexing"
        logger.info("Background Indexing: running AST indexer script...")

        # Find absolute path of index_repo.py
        indexer_script = os.path.join(os.path.dirname(__file__), "index_repo.py")
        if not os.path.exists(indexer_script):
            # Fallback if working dir or path is shifted
            indexer_script = os.path.join(os.path.dirname(__file__), "..", "index_repo.py")

        indexer_cmd = [
            sys.executable,
            indexer_script,
            "--repo-path", clone_path,
            "--repo-name", repo
        ]

        res_idx = subprocess.run(indexer_cmd, capture_output=True, text=True, timeout=300)
        if res_idx.returncode != 0:
            raise RuntimeError(f"Indexer failed: {res_idx.stderr}\nStdout: {res_idx.stdout}")

        chunks = _check_qdrant_indexed_chunks(repo)
        _indexing_state["chunks_count"] = chunks
        _indexing_state["status"] = "completed"
        logger.info(f"Background Indexing completed. Chunks count: {chunks}")

    except Exception as exc:
        logger.error(f"Background Indexing failed: {exc}")
        _indexing_state["status"] = "failed"
        _indexing_state["error"] = str(exc)
    finally:
        if os.path.exists(clone_path):
            shutil.rmtree(clone_path, ignore_errors=True)


@app.get("/config")
def get_config():
    """Returns active repository connection status (exposing no token)."""
    # Check if we already have chunks indexed in Qdrant
    indexed = False
    chunks_count = 0
    if _active_repo:
        chunks_count = _check_qdrant_indexed_chunks(_active_repo)
        indexed = chunks_count > 0

    return {
        "repo": _active_repo,
        "status": _active_status,
        "indexed": indexed,
        "chunks_count": chunks_count,
        "indexing_state": _indexing_state
    }


@app.post("/config")
def save_config(req: ConfigSaveRequest):
    """Tests connection to GitHub using provided PAT, and saves it in backend memory."""
    global _active_repo, _active_token, _active_status, _indexing_state
    
    # Try fetching open PRs to test connection
    from github_client import fetch_open_prs
    try:
        fetch_open_prs(req.repo, req.token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Authentication failed: {exc}")

    _active_repo = req.repo.strip()
    _active_token = req.token.strip()
    _active_status = "connected"

    # Reset indexing state for the new repository
    if _indexing_state["repo"] != _active_repo:
        _indexing_state = {
            "status": "idle",
            "repo": _active_repo,
            "chunks_count": 0,
            "error": None
        }

    return {"status": "connected", "repo": _active_repo}


@app.post("/config/disconnect")
def disconnect_config():
    """Disconnects and clears active repository credentials from memory."""
    global _active_repo, _active_token, _active_status, _indexing_state
    _active_repo = ""
    _active_token = ""
    _active_status = "disconnected"
    _indexing_state = {
        "status": "idle",
        "repo": "",
        "chunks_count": 0,
        "error": None
    }
    return {"status": "disconnected"}


@app.get("/config/indexing-status")
def get_indexing_status():
    """Returns current repository indexing state and Qdrant points count."""
    global _indexing_state
    if not _active_repo:
        return {"status": "idle", "chunks_count": 0}

    # Query Qdrant to find if it is already indexed
    chunks = _check_qdrant_indexed_chunks(_active_repo)
    if _indexing_state["status"] == "idle" and chunks > 0:
        _indexing_state["status"] = "completed"
        _indexing_state["chunks_count"] = chunks
        _indexing_state["repo"] = _active_repo

    return {
        "status": _indexing_state["status"],
        "repo": _active_repo,
        "chunks_count": chunks,
        "error": _indexing_state["error"]
    }


@app.post("/config/index")
def trigger_indexing(background_tasks: BackgroundTasks):
    """Queues background cloning & AST indexing for active connected repository."""
    if _active_status != "connected":
        raise HTTPException(status_code=400, detail="No active repository connection.")
    
    if _indexing_state["status"] in ("cloning", "indexing"):
        return {"message": "Indexing is already running in background."}

    background_tasks.add_task(_run_background_indexing, _active_repo, _active_token)
    return {"message": "Indexing queued."}


@app.get("/config/prs")
def get_open_prs():
    """Lists open pull requests for the active connected repository."""
    if _active_status != "connected":
        raise HTTPException(status_code=400, detail="No active repository connection.")
    
    from github_client import fetch_open_prs
    try:
        return fetch_open_prs(_active_repo, _active_token)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch open PRs: {exc}")



@app.post("/config/trigger-review")
def trigger_review_from_config(req: TriggerReviewRequest, background_tasks: BackgroundTasks):
    """Triggers review for a PR on the active repository using secure memory PAT."""
    if _active_status != "connected":
        raise HTTPException(status_code=400, detail="No active repository connection.")

    from github_client import get_pr_head_sha
    try:
        commit_sha = get_pr_head_sha(_active_repo, req.pr_number, _active_token)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch PR branch metadata: {exc}")

    idempotency_key = (_active_repo, req.pr_number, commit_sha)

    from database import SessionLocal
    from models import Review
    db = SessionLocal()
    try:
        if db.query(Review).filter_by(repo=_active_repo, pr_number=req.pr_number, commit_sha=commit_sha).first():
            return {"status": "already_reviewed", "message": "Already reviewed."}
    finally:
        db.close()

    if idempotency_key in _in_progress_commits:
        return {"status": "in_progress", "message": "Review already in progress."}

    _in_progress_commits.add(idempotency_key)
    background_tasks.add_task(
        process_pr_review,
        repo=_active_repo,
        pr_number=req.pr_number,
        commit_sha=commit_sha,
        token=_active_token,
        source="manual",
    )

    return {"status": "queued", "message": "Review queued in background."}


