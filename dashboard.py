import os
import streamlit as st
import pandas as pd
import requests
import time

from streamlit_autorefresh import st_autorefresh

# Set page configuration for professional premium feel
st.set_page_config(
    page_title="🤖 PR Review Agent Portal",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Backend API Configuration
API_URL = os.environ.get("API_URL", "http://localhost:8000")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ---------------------------------------------------------------------------
# EVENT-DRIVEN REFRESH: only rerun when backend has new data
# ---------------------------------------------------------------------------
# Poll the lightweight /status endpoint every 10 seconds.
# If last_review_at hasn't changed since our last check, do nothing.
# Only call st.rerun() when a new review has been persisted or one is in progress.

if "last_seen_review_at" not in st.session_state:
    st.session_state.last_seen_review_at = None

# Lightweight status check (just a timestamp, no heavy DB query)
try:
    _status_resp = requests.get(f"{API_URL}/status", timeout=2)
    if _status_resp.status_code == 200:
        _status = _status_resp.json()
        _new_review_at = _status.get("last_review_at", "")
        _in_progress = _status.get("in_progress", False)

        if _in_progress:
            # Review is actively running — poll fast (every 5s via autorefresh)
            st_autorefresh(interval=5000, key="portal_autorefresh")
        elif _new_review_at != st.session_state.last_seen_review_at:
            # A new review just finished — update our cache and rerun to show it
            st.session_state.last_seen_review_at = _new_review_at
            st_autorefresh(interval=30000, key="portal_autorefresh")
        else:
            # Nothing new — refresh every 30s just to stay alive, but won't change anything
            st_autorefresh(interval=30000, key="portal_autorefresh")
    else:
        st_autorefresh(interval=30000, key="portal_autorefresh")
except Exception:
    st_autorefresh(interval=30000, key="portal_autorefresh")

# Also check for in-progress jobs for the sidebar indicator
in_progress_jobs = []
try:
    in_progress_resp = requests.get(f"{API_URL}/reviews/in-progress", timeout=2)
    if in_progress_resp.status_code == 200:
        in_progress_jobs = in_progress_resp.json()
except Exception:
    pass


# Custom CSS for modern premium SaaS look (dark themes, custom cards, metrics, buttons)
st.markdown("""
<style>
    /* Global styles */
    .stApp {
        background-color: #0b0f19;
        color: #f1f5f9;
    }
    
    /* Segment titles */
    h1, h2, h3 {
        color: #f8fafc !important;
        font-family: 'Inter', -apple-system, sans-serif;
    }
    
    /* Onboarding & Card styling */
    .saas-card {
        background-color: #131b2e;
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 24px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    .welcome-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #38bdf8;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 28px;
    }
    
    /* Metrics panel */
    .metric-box {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 16px 20px;
        text-align: center;
    }
    .metric-num {
        font-size: 28px;
        font-weight: 700;
        color: #38bdf8;
    }
    .metric-lbl {
        font-size: 13px;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-top: 4px;
    }
    
    /* Workflow flowcharts */
    .flowchart-step {
        background-color: #1e293b;
        border: 1px solid #475569;
        border-radius: 6px;
        padding: 8px 12px;
        text-align: center;
        font-size: 12px;
        font-weight: 600;
        color: #e2e8f0;
    }
    .flowchart-arrow {
        text-align: center;
        font-size: 18px;
        color: #38bdf8;
        margin: 4px 0;
    }
    
    /* Badges & Status */
    .status-dot {
        height: 10px;
        width: 10px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 8px;
    }
    .dot-green { background-color: #10b981; }
    .dot-yellow { background-color: #f59e0b; }
    .dot-red { background-color: #ef4444; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# API HELPER FUNCTIONS
# ---------------------------------------------------------------------------

def get_backend_config():
    """Fetches connection status, active repo, and indexing state from backend."""
    try:
        resp = requests.get(f"{API_URL}/config", timeout=4)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def get_health_status():
    """Queries health endpoint to determine status of databases/Ollama."""
    try:
        resp = requests.get(f"{API_URL}/health", timeout=3)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def get_all_reviews(include_archived: bool = False):
    """Fetches all review logs from the FastAPI backend."""
    try:
        resp = requests.get(f"{API_URL}/reviews", params={"include_archived": include_archived}, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_pr_status(repo: str, pr_number: int, token: str | None) -> str:
    """Queries GitHub API for the state/merged status of a pull request."""
    if not repo or "/" not in repo:
        return "unknown"
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-Review-Agent/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token.strip()}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("merged") is True:
                return "merged"
            return data.get("state", "unknown")
    except Exception:
        pass
    return "unknown"



# ---------------------------------------------------------------------------
# STATE & POLLING CONTROLS
# ---------------------------------------------------------------------------

# Initialize local toggle variables
if "show_reconnect_form" not in st.session_state:
    st.session_state.show_reconnect_form = False

if "pr_status_cache" not in st.session_state:
    st.session_state.pr_status_cache = {}

if "connected_token" not in st.session_state:
    st.session_state.connected_token = None

# Fetch backend state on load
config = get_backend_config()
health = get_health_status()

# Determine statuses for indicators
is_github_connected = False
is_db_connected = False
is_qdrant_connected = False
is_ollama_connected = False
is_kb_ready = False

if config:
    is_github_connected = config.get("status") == "connected"
    is_kb_ready = config.get("indexed", False)

if health:
    is_db_connected = health.get("database_connected", False)
    # Check if Qdrant is connected (if database is connected and we can fetch collections)
    is_qdrant_connected = health.get("database_connected", False)
    is_ollama_connected = health.get("token_configured", False) or True  # Default fallback if Ollama active


# ---------------------------------------------------------------------------
# SIDEBAR STATUS PANEL
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## System Status")
    st.markdown("Real-time telemetry and infrastructure status:")

    # GitHub Status
    gh_class = "dot-green" if is_github_connected else "dot-red"
    gh_label = "Connected" if is_github_connected else "Disconnected"
    st.markdown(f'<div class="saas-card" style="padding: 12px; margin-bottom: 12px;">'
                f'<span class="status-dot {gh_class}"></span>GitHub: <b>{gh_label}</b>'
                f'</div>', unsafe_allow_html=True)

    # Postgres Status
    pg_class = "dot-green" if is_db_connected else "dot-red"
    pg_label = "Connected" if is_db_connected else "Offline"
    st.markdown(f'<div class="saas-card" style="padding: 12px; margin-bottom: 12px;">'
                f'<span class="status-dot {pg_class}"></span>PostgreSQL: <b>{pg_label}</b>'
                f'</div>', unsafe_allow_html=True)

    # Qdrant Status
    qd_class = "dot-green" if is_qdrant_connected else "dot-red"
    qd_label = "Connected" if is_qdrant_connected else "Offline"
    st.markdown(f'<div class="saas-card" style="padding: 12px; margin-bottom: 12px;">'
                f'<span class="status-dot {qd_class}"></span>Qdrant: <b>{qd_label}</b>'
                f'</div>', unsafe_allow_html=True)

    # Ollama Status
    ol_class = "dot-green" if is_ollama_connected else "dot-yellow"
    ol_label = "Active" if is_ollama_connected else "Warning"
    st.markdown(f'<div class="saas-card" style="padding: 12px; margin-bottom: 12px;">'
                f'<span class="status-dot {ol_class}"></span>Ollama: <b>{ol_label}</b>'
                f'</div>', unsafe_allow_html=True)

    # Knowledge Base Status
    kb_class = "dot-green" if is_kb_ready else "dot-red"
    kb_label = "Indexed" if is_kb_ready else "Not Indexed"
    st.markdown(f'<div class="saas-card" style="padding: 12px; margin-bottom: 12px;">'
                f'<span class="status-dot {kb_class}"></span>Knowledge Base: <b>{kb_label}</b>'
                f'</div>', unsafe_allow_html=True)

    st.markdown("---")
    st.caption("🤖 PR Review Agent v1.0.0 — Production Build")


# ---------------------------------------------------------------------------
# ONBOARDING / FIRST LAUNCH CARD
# ---------------------------------------------------------------------------

if not is_github_connected:
    st.markdown(
        """
        <div class="welcome-card">
            <h3>👋 Welcome to the PR Review Agent Portal!</h3>
            <p>This SaaS portal automates code quality, security audits, and RAG context reviews directly on your PRs.</p>
            <p><b>Get started in minutes by following these simple steps:</b></p>
            <ol>
                <li>🔌 <b>Connect GitHub Repository</b> — Authenticate with your GitHub Personal Access Token (PAT).</li>
                <li>🧠 <b>Build AI Knowledge Base (RAG)</b> — Allow the agent to parse, embed, and index your repository code.</li>
                <li>📥 <b>Load Pull Requests</b> — List your open branch changes directly from the UI.</li>
                <li>🤖 <b>Review Pull Requests</b> — Trigger high-quality, local LLM-reviews and post comments.</li>
            </ol>
        </div>
        """,
        unsafe_allow_html=True
    )


# ---------------------------------------------------------------------------
# STEP 1: CONNECT GITHUB REPOSITORY
# ---------------------------------------------------------------------------

st.markdown("## 1. Connect GitHub Repository")
st.markdown("Provide repository specifications and authentication details to connect the portal to GitHub.")

# Display credentials inputs if disconnected, or if "Reconnect" is clicked
if not is_github_connected or st.session_state.show_reconnect_form:
    st.markdown(
        """
        <div class="saas-card" style="padding: 16px; margin-bottom: 16px; background-color: #1a2333;">
            <p style="margin: 0; font-size: 13px; color: #94a3b8;">
                💡 <b>How to get your PAT:</b> Go to your GitHub profile settings → <b>Developer Settings</b> → 
                <b>Personal Access Tokens (classic)</b> → Click <b>Generate new token</b>. Select the <b>repo</b> scope 
                (which grants full control of private/public repositories).
            </p>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    col_repo, col_pat = st.columns(2)
    with col_repo:
        repo_input = st.text_input(
            "Repository path (owner/repo name):",
            placeholder="e.g. facebook/react"
        )
    with col_pat:
        pat_input = st.text_input(
            "GitHub Personal Access Token (PAT):",
            type="password",
            placeholder="ghp_..."
        )

    col_btn_conn, _ = st.columns([1, 4])
    with col_btn_conn:
        if st.button("Connect Repository", type="primary"):
            if not repo_input or not pat_input:
                st.error("Please fill in both fields.")
            else:
                with st.spinner("Authenticating with GitHub..."):
                    try:
                        payload = {"repo": repo_input.strip(), "token": pat_input.strip()}
                        resp = requests.post(f"{API_URL}/config", json=payload, timeout=10)
                        if resp.status_code == 200:
                            st.success("Successfully authenticated and connected!")
                            st.session_state.connected_token = pat_input.strip()
                            st.session_state.show_reconnect_form = False
                            st.rerun()
                        else:
                            st.error(f"Authentication failed: {resp.json().get('detail', 'Unknown error')}")
                    except Exception as e:
                        st.error(f"Network error: {e}")
else:
    # Repository is connected: display status card instead of raw inputs
    st.markdown(
        f"""
        <div class="saas-card" style="border-left-color: #10b981; background-color: #111827; padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <h4 style="margin: 0; color: #10b981;">✓ Connected to GitHub</h4>
                    <p style="margin: 6px 0 0 0; font-size: 15px;">Repository: <b>{config.get('repo')}</b></p>
                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #94a3b8;">Status: Connected & Authenticated</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    col_reconn, col_disc, _ = st.columns([1, 1, 4])
    with col_reconn:
        if st.button("Reconnect Repository"):
            st.session_state.show_reconnect_form = True
            st.rerun()
    with col_disc:
        if st.button("Disconnect", type="primary"):
            try:
                resp = requests.post(f"{API_URL}/config/disconnect")
                if resp.status_code == 200:
                    st.success("Disconnected repository credentials.")
                    st.session_state.connected_token = None
                    st.session_state.show_reconnect_form = False
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to disconnect: {e}")

st.markdown("---")


# ---------------------------------------------------------------------------
# STEP 2: BUILD AI KNOWLEDGE BASE (RAG)
# ---------------------------------------------------------------------------

st.markdown("## 2. Build AI Knowledge Base (RAG)")
st.markdown("Create a local semantic code index of your repository so the review agent understands file layouts and functions.")

col_rag_flow, col_rag_info = st.columns([1, 2])

with col_rag_flow:
    st.markdown(
        """
        <div class="saas-card" style="padding: 16px; background-color: #0f172a;">
            <div class="flowchart-step">GitHub Repository</div>
            <div class="flowchart-arrow">↓</div>
            <div class="flowchart-step">Clone Repository</div>
            <div class="flowchart-arrow">↓</div>
            <div class="flowchart-step">AST Parser</div>
            <div class="flowchart-arrow">↓</div>
            <div class="flowchart-step">Semantic Code Chunks</div>
            <div class="flowchart-arrow">↓</div>
            <div class="flowchart-step">nomic-embed-text</div>
            <div class="flowchart-arrow">↓</div>
            <div class="flowchart-step">Qdrant Vector DB</div>
        </div>
        """,
        unsafe_allow_html=True
    )

with col_rag_info:
    st.markdown(
        """
        <p style="font-size: 15px; line-height: 1.6; color: #cbd5e1;">
            <b>"The AI learns the existing codebase before reviewing Pull Requests so it understands the surrounding code instead of reviewing only the changed lines."</b>
        </p>
        <p style="font-size: 13.5px; color: #94a3b8;">
            By indexing Python declarations (classes, functions, decorators) using an Abstract Syntax Tree (AST), the review loop queries Qdrant Vector database to retrieve structural codebase reference during analysis tasks.
        </p>
        """,
        unsafe_allow_html=True
    )
    
    # Auto-indexing loop
    if is_github_connected:
        try:
            status_resp = requests.get(f"{API_URL}/config/indexing-status").json()
            idx_status = status_resp.get("status", "idle")
            idx_chunks = status_resp.get("chunks_count", 0)
            
            if idx_status == "idle" and idx_chunks == 0:
                # Never indexed: automatically begin indexing
                st.info("Repository has not been indexed yet. Starting indexing automatically...")
                requests.post(f"{API_URL}/config/index")
                st.rerun()
                
            elif idx_status in ("cloning", "indexing"):
                # Indexing is in progress, poll updates
                status_text = "Cloning Repository..." if idx_status == "cloning" else "Extracting AST functions & generating embeddings..."
                st.markdown(f"**Status:** ⚙️ *{status_text}*")
                st.progress(0.4 if idx_status == "cloning" else 0.75)
                time.sleep(2)
                st.rerun()
                
            elif idx_status == "completed" or idx_chunks > 0:
                # Indexing completed successfully
                st.markdown(
                    f"""
                    <div style="background-color: #111827; border: 1px solid #10b981; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
                        <h5 style="margin: 0; color: #10b981;">✓ Knowledge Base Ready</h5>
                        <p style="margin: 6px 0 0 0; font-size: 13.5px; color: #cbd5e1;">Repository: <b>{config.get('repo')}</b></p>
                        <p style="margin: 3px 0 0 0; font-size: 13.5px; color: #cbd5e1;">Collection: <b>pr_reviews</b></p>
                        <p style="margin: 3px 0 0 0; font-size: 13.5px; color: #cbd5e1;">Semantic Chunks: <b>{idx_chunks} chunks loaded</b></p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                if st.button("Re-index Repository", help="Re-runs indexing to synchronize local codebase context"):
                    requests.post(f"{API_URL}/config/index")
                    st.rerun()
                    
            elif idx_status == "failed":
                st.error("Indexing failed.")
                st.code(status_resp.get("error", "Unknown error occurred."))
                if st.button("Retry Indexing"):
                    requests.post(f"{API_URL}/config/index")
                    st.rerun()
        except Exception as e:
            st.error(f"Error checking indexing status: {e}")
    else:
        st.markdown(
            """
            <div style="background-color: #1e293b; border-radius: 8px; padding: 16px; text-align: center;">
                <p style="margin: 0; color: #94a3b8; font-size: 14px;">🔌 Connect a GitHub repository in Step 1 to build the Knowledge Base.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

st.markdown("---")


# ---------------------------------------------------------------------------
# STEP 3: LOAD OPEN PULL REQUESTS
# ---------------------------------------------------------------------------

st.markdown("## 3. Open Pull Requests")
st.markdown("Load and review active pull requests for the connected repository.")

with st.expander("📖 Understanding Review Verdicts & Statuses"):
    st.markdown(
        """
        Here is how the AI agent determines and displays the code review verdicts:
        
        *   🟢 **`APPROVE`** — **Approved.** The code is clean, syntax is correct, Ruff linter and Bandit security scan pass with zero violations, and the LLM determines it is safe to merge.
        *   🟡 **`COMMENT_ONLY`** — **Not Approved (Neutral).** The agent left helpful comments, optimization ideas, or queries. The author should address them, but there are no critical blocking bugs.
        *   🔴 **`REQUEST_CHANGES`** — **Blocked.** The agent detected code bugs, linting failures, syntax issues, or critical security vulnerabilities (e.g. hardcoded secrets). The PR is blocked until these are resolved.
        
        *Note: In the Analytics Dashboard, only the **`APPROVE`** verdict counts toward the **Approval Rate**.*
        """
    )

if is_github_connected:

    try:
        # Load open PRs
        prs_resp = requests.get(f"{API_URL}/config/prs")
        if prs_resp.status_code == 200:
            prs = prs_resp.json()
            
            if not prs:
                st.markdown(
                    """
                    <div style="background-color: #111827; border: 1px dashed #475569; border-radius: 8px; padding: 32px; text-align: center;">
                        <h4 style="margin: 0; color: #94a3b8;">No Open Pull Requests Found</h4>
                        <p style="margin: 8px 0 0 0; font-size: 13.5px; color: #64748b;">
                            There are currently no open pull requests in this repository.<br>
                            To test, create a branch in your repository, make some changes, and open a PR on GitHub.
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
            else:
                for pr in prs:
                    st.markdown(
                        f"""
                        <div class="saas-card" style="margin-bottom: 12px; padding: 16px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <h4 style="margin: 0; font-size: 16px;">PR #{pr['number']}: {pr['title']}</h4>
                                    <p style="margin: 6px 0 0 0; font-size: 13px; color: #94a3b8;">
                                        Author: <b>@{pr['user']}</b> &nbsp;|&nbsp; Branch: <code>{pr.get('branch', 'main')}</code>
                                    </p>
                                    <p style="margin: 3px 0 0 0; font-size: 11px; color: #64748b;">Head SHA: <code>{pr['head_sha']}</code></p>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    # Triggers for reviews
                    col_review, col_status = st.columns([1, 4])
                    with col_review:
                        review_btn_key = f"review_{pr['number']}"
                        is_reviewing = st.session_state.get(f"running_{pr['number']}", False)
                        
                        # Disabled check
                        disable_review = not is_kb_ready or is_reviewing
                        tooltip_text = "Wait for knowledge base indexing to complete" if not is_kb_ready else "Trigger AI review analysis"
                        
                        if st.button(
                            "🤖 Run Review",
                            key=review_btn_key,
                            disabled=disable_review,
                            help=tooltip_text
                        ):
                            st.session_state[f"running_{pr['number']}"] = True
                            st.rerun()
                            
                    with col_status:
                        if is_reviewing:
                            st.markdown("⚙️ Reviewing in progress. Follow live execution below in Step 4.")
        else:
            st.error(f"Failed to fetch pull requests: {prs_resp.text}")
    except Exception as e:
        st.error(f"Failed to connect to backend: {e}")
else:
    st.markdown(
        """
        <div style="background-color: #1e293b; border-radius: 8px; padding: 16px; text-align: center;">
            <p style="margin: 0; color: #94a3b8; font-size: 14px;">🔌 Connect a GitHub repository in Step 1 to load Pull Requests.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")


# ---------------------------------------------------------------------------
# STEP 4: AI REVIEW LIVE PROGRESS
# ---------------------------------------------------------------------------

st.markdown("## 4. AI Review Execution Logs")
st.markdown("Track the live telemetry of review jobs sent to the backend.")

# Check if any review job is actively running in UI session state
running_prs = [k for k, v in st.session_state.items() if k.startswith("running_") and v]

if running_prs:
    active_pr_key = running_prs[0]
    pr_num = int(active_pr_key.split("_")[1])
    
    st.markdown(f"### ⚙️ Running AI Review for PR #{pr_num}")
    
    # Start actual endpoint review call in the background instantly
    with st.spinner("FastAPI Backend is running analysis tasks (Ruff, Bandit, Qdrant search, qwen2.5-coder)..."):
        try:
            # Submit review trigger
            payload = {"pr_number": pr_num}
            resp = requests.post(f"{API_URL}/config/trigger-review", json=payload, timeout=45)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "queued":
                    st.success(f"✓ AI Review queued successfully for PR #{pr_num}! The agent is analyzing the code in the background. The logs and analytics below will update automatically.")
                elif data.get("status") == "already_reviewed":
                    st.info("✓ This commit state has already been reviewed. Loaded verdict from DB.")
                else:
                    st.warning(data.get("message"))
            else:
                st.error(f"Review failed: {resp.text}")
        except Exception as exc:
            st.error(f"Failed to execute review: {exc}")
        finally:
            st.session_state[active_pr_key] = False
            # Force refresh to update analytics metrics
            st.cache_data.clear()
            st.rerun()

elif in_progress_jobs:
    # Active background review jobs executing in the backend
    st.markdown("### ⚙️ Background AI Review in Progress")
    for job in in_progress_jobs:
        st.info(f"⏳ **Active Review** for {job['repo']} PR #{job['pr_number']} (commit {job['commit_sha'][:7]}) is currently executing in the background. The dashboard will automatically update once it finishes.")
    # Display animated spinner
    st.spinner("Running code analysis & context verification...")

else:
    st.markdown(
        """
        <div style="background-color: #111827; border: 1px dashed #334155; border-radius: 8px; padding: 24px; text-align: center;">
            <p style="margin: 0; color: #64748b; font-size: 13.5px;">No active review jobs running. Click "Run Review" on any PR card in Step 3.</p>
        </div>
        """,
        unsafe_allow_html=True
    )

# Detailed Reasoning Inspector (placed just below Step 4)
st.markdown("### 🔍 Detailed Reasoning Inspector")
all_reviews = get_all_reviews()
if all_reviews:
    # Auto-switch to index 0 (newest) if a new review has completed
    newest_id = all_reviews[0]["id"]
    if st.session_state.get("last_newest_review_id") != newest_id:
        st.session_state.last_newest_review_id = newest_id
        st.session_state.inspector_selected_index = 0
        st.cache_data.clear()
    
    selected_idx = st.selectbox(
        "Select a review record to inspect details:",
        range(len(all_reviews)),
        index=st.session_state.get("inspector_selected_index", 0),
        format_func=lambda idx: f"{all_reviews[idx]['repo']} PR #{all_reviews[idx]['pr_number']} ({all_reviews[idx]['decision']})",
        key="inspector_under_step4"
    )
    # Persist the user's manual selection
    st.session_state.inspector_selected_index = selected_idx
    
    if selected_idx is not None and selected_idx < len(all_reviews):
        row = all_reviews[selected_idx]
        st.markdown(f"**Verdict:** `{row['decision']}`")
        st.markdown(f"**PR Relevance:** {row.get('relevance', '✅ Relevant')}")
        st.markdown(f"**Summary:** {row['summary']}")
        st.markdown("**Reasoning Details:**")
        st.code(row["reason"], language="markdown")
else:
    st.info("No reviews available to inspect yet.")

st.markdown("---")



# ---------------------------------------------------------------------------
# STEP 5: ANALYTICS DASHBOARD
# ---------------------------------------------------------------------------

st.markdown("## 5. Analytics Dashboard")
st.markdown("Historical overview and detailed records of PR reviews rendered by the agent.")

if config:
    show_archived = st.checkbox("Show archived reviews", value=False, help="Show soft-deleted/archived reviews in history and analytics")
    reviews_list = get_all_reviews(include_archived=show_archived)
    
    if reviews_list:
        df_rev = pd.DataFrame(reviews_list)
        df_rev["created_at"] = pd.to_datetime(df_rev["created_at"])
        
        # Local UI Filtering
        repos_filter = ["All"] + sorted(df_rev["repo"].unique().tolist())
        verdicts_filter = ["All"] + sorted(df_rev["decision"].unique().tolist())
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            sel_repo = st.selectbox("Repository Filter:", repos_filter)
        with col_f2:
            sel_verd = st.selectbox("Verdict Filter:", verdicts_filter)
            
        filtered_rev = df_rev.copy()
        if sel_repo != "All":
            filtered_rev = filtered_rev[filtered_rev["repo"] == sel_repo]
        if sel_verd != "All":
            filtered_rev = filtered_rev[filtered_rev["decision"] == sel_verd]
            
        total_count = len(filtered_rev)
        
        # Fetch GitHub state for visible rows if not cached
        for _, row in filtered_rev.iterrows():
            key = (row["repo"], int(row["pr_number"]))
            if key not in st.session_state.pr_status_cache:
                token_to_use = st.session_state.get("connected_token") if is_github_connected else GITHUB_TOKEN
                st.session_state.pr_status_cache[key] = fetch_pr_status(row["repo"], int(row["pr_number"]), token_to_use)
        
        # Calculate rates
        if total_count > 0:
            approves = len(filtered_rev[filtered_rev["decision"] == "APPROVE"])
            comments = len(filtered_rev[filtered_rev["decision"] == "COMMENT_ONLY"])
            changes = len(filtered_rev[filtered_rev["decision"] == "REQUEST_CHANGES"])
            app_rate = (approves / total_count) * 100
        else:
            approves = comments = changes = app_rate = 0
            
        # Display professional metrics cards
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.markdown(f'<div class="metric-box"><div class="metric-num">{total_count}</div><div class="metric-lbl">Total Reviews</div></div>', unsafe_allow_html=True)
        with col_m2:
            st.markdown(f'<div class="metric-box" style="border-left-color: #10b981;"><div class="metric-num" style="color: #10b981;">{app_rate:.1f}%</div><div class="metric-lbl">Approval Rate</div></div>', unsafe_allow_html=True)
        with col_m3:
            st.markdown(f'<div class="metric-box" style="border-left-color: #f59e0b;"><div class="metric-num" style="color: #f59e0b;">{comments}</div><div class="metric-lbl">Comment Only</div></div>', unsafe_allow_html=True)
        with col_m4:
            st.markdown(f'<div class="metric-box" style="border-left-color: #ef4444;"><div class="metric-num" style="color: #ef4444;">{changes}</div><div class="metric-lbl">Request Changes</div></div>', unsafe_allow_html=True)
            
        st.markdown("### 📊 Decision Distribution")
        if total_count > 0:
            import altair as alt
            chart_df = filtered_rev["decision"].value_counts().reset_index()
            chart_df.columns = ["Verdict", "Count"]
            chart = alt.Chart(chart_df).mark_bar(color="#3b82f6").encode(
                x=alt.X("Verdict:N", title="Verdict", sort="-y"),
                y=alt.Y("Count:Q", title="Count", axis=alt.Axis(tickMinStep=1, format="d")),
                tooltip=["Verdict", "Count"]
            ).properties(height=350)
            st.altair_chart(chart, use_container_width=True)
            
            # Review records listing
            col_tbl_hdr, col_tbl_btn = st.columns([4, 1])
            with col_tbl_hdr:
                st.markdown("### 📋 Review History logs")
            with col_tbl_btn:
                if st.button("🗑️ Clear History", key="clear_history_btn"):
                    st.session_state.show_archive_confirm = True

            if st.session_state.get("show_archive_confirm"):
                st.warning(f"⚠️ Are you sure you want to clear/archive these {total_count} visible review(s)? This will hide them from the default view.")
                col_c1, col_c2 = st.columns(2)
                with col_c1:
                    if st.button("Yes, Confirm Clear", key="confirm_clear_btn"):
                        ids_to_archive = filtered_rev["id"].tolist()
                        try:
                            archive_resp = requests.post(f"{API_URL}/reviews/archive", json={"ids": ids_to_archive}, timeout=10)
                            if archive_resp.status_code == 200:
                                st.success(f"Archived {len(ids_to_archive)} reviews.")
                                st.session_state.show_archive_confirm = False
                                st.rerun()
                            else:
                                st.error(f"Failed to archive: {archive_resp.text}")
                        except Exception as e:
                            st.error(f"Connection failed: {e}")
                with col_c2:
                    if st.button("Cancel", key="cancel_clear_btn"):
                        st.session_state.show_archive_confirm = False
                        st.rerun()

            display_cols = filtered_rev[["repo", "pr_number", "commit_sha", "decision", "relevance", "summary", "created_at"]].copy()
            if "source" in filtered_rev.columns:
                display_cols["repo"] = filtered_rev.apply(
                    lambda row: f"🧪 [TEST] {row['repo']}" if row.get('source') == 'batch_test' else row['repo'],
                    axis=1
                )
            
            # Populate Live PR Status column
            def get_pr_status_badge(status_str: str) -> str:
                if status_str == "merged":
                    return "🟢 Merged"
                elif status_str == "closed":
                    return "🔴 Closed"
                elif status_str == "open":
                    return "🟡 Open"
                else:
                    return "⚪ Unknown"

            display_cols["PR Status"] = [
                get_pr_status_badge(st.session_state.pr_status_cache.get((row["repo"], int(row["pr_number"])), "unknown"))
                for _, row in filtered_rev.iterrows()
            ]

            st.dataframe(
                display_cols.sort_values(by="created_at", ascending=False),
                width="stretch",
                column_config={
                    "repo": "Repository",
                    "pr_number": "PR ID",
                    "commit_sha": "Commit SHA",
                    "decision": "Verdict",
                    "relevance": "Relevance",
                    "summary": "Summary",
                    "PR Status": "PR Status",
                    "created_at": "Timestamp"
                }
            )
            

        else:
            st.info("No records match the filter criteria.")
    else:
        st.info("No reviews stored in the database. Trigger a review in Step 3.")
else:
    st.markdown(
        """
        <div style="background-color: #1e293b; border-radius: 8px; padding: 16px; text-align: center;">
            <p style="margin: 0; color: #94a3b8; font-size: 14px;">🔌 Connect repository and review PRs to view analytics.</p>
        </div>
        """,
        unsafe_allow_html=True
    )



