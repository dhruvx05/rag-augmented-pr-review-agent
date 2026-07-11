import json
import os
import requests
from tools import run_lint, run_security_scan

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_CHAT_URL = f"{OLLAMA_HOST}/api/chat"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
RAG_COLLECTION = "pr_reviews"
LLM_MODEL = "qwen2.5-coder:7b"
EMBED_MODEL = "nomic-embed-text"
RAG_CONTEXT_CHAR_BUDGET = 4000

# --- Review verdict schema ---

VERDICT_SCHEMA_HINT = (
    "{\n"
    '  "decision": "APPROVE" | "COMMENT_ONLY" | "REQUEST_CHANGES",\n'
    '  "relevance": "✅ Relevant | ⚠️ Partially Relevant | ❌ Out of Scope - followed by reasons.",\n'
    '  "reason": "Detailed review explanation referencing specific files and lines.",\n'
    '  "summary": "A concise, dynamic 1-2 sentence summary of the specific code changes introduced in this PR and their main purpose.",\n'
    '  "security_flags": [\n'
    '    { "file": "path/to/file.py", "issue": "description", "severity": "LOW|MEDIUM|HIGH", "line": 42 }\n'
    "  ]\n"
    "}"
)

VALID_DECISIONS = {"APPROVE", "COMMENT_ONLY", "REQUEST_CHANGES"}


# ---------------------------------------------------------------------------
# RAG context retrieval
# ---------------------------------------------------------------------------

def _extract_added_lines(diff_files: list[dict]) -> str:
    """Builds a query string from added lines across all changed files."""
    segments = []
    for f in diff_files:
        patch = f.get("patch_text", "")
        added = [line[1:] for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")]
        segments.append(f"File: {f['file_path']}\n" + ("\n".join(added) if added else patch))
    return "\n\n".join(segments)


def _get_query_embedding(query_text: str) -> list[float] | None:
    """Returns a vector embedding for the given text, or None on failure."""
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": query_text},
            timeout=10,
        )
        if resp.status_code in (400, 404):
            print(f"[Warning] Embedding model '{EMBED_MODEL}' unavailable: {resp.text}")
            return None
        resp.raise_for_status()
        return resp.json()["embedding"]
    except Exception as exc:
        print(f"[Warning] Failed to generate query embedding: {exc}")
        return None


def retrieve_related_context(diff_files: list[dict], repo: str, k: int = 3) -> str:
    """
    Queries Qdrant for the top-k code chunks most semantically similar to the PR diff.

    Returns:
        A formatted multi-chunk string, or an empty string if retrieval fails.
    """
    if not repo:
        return ""

    query_text = _extract_added_lines(diff_files)
    if not query_text:
        return ""

    query_vector = _get_query_embedding(query_text)
    if not query_vector:
        return ""

    try:
        # Verify collection exists before searching.
        check = requests.get(f"{QDRANT_URL}/collections/{RAG_COLLECTION}", timeout=5)
        if check.status_code != 200:
            print(f"[Warning] Qdrant collection '{RAG_COLLECTION}' not found. Skipping RAG.")
            return ""

        resp = requests.post(
            f"{QDRANT_URL}/collections/{RAG_COLLECTION}/points/search",
            json={
                "vector": query_vector,
                "filter": {"must": [{"key": "repo", "match": {"value": repo}}]},
                "limit": k,
                "with_payload": True,
            },
            timeout=5,
        )
        resp.raise_for_status()
        results = resp.json().get("result", [])

        if not results:
            return ""

        chunks = []
        for idx, pt in enumerate(results, start=1):
            p = pt.get("payload", {})
            chunks.append(
                f"### Related Chunk {idx}\n"
                f"**File**: {p.get('file_path', 'unknown')} "
                f"(Lines {p.get('start_line', 0)}–{p.get('end_line', 0)})\n"
                f"**Entity**: {p.get('function_name', 'unknown')}\n"
                f"```python\n{p.get('content', '')}\n```"
            )
        return "\n\n".join(chunks)

    except Exception as exc:
        print(f"[Warning] Failed to query Qdrant RAG context: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Diff formatting
# ---------------------------------------------------------------------------

def format_diff(diff_files: list[dict]) -> str:
    """Formats a list of PR file diffs into a single readable string for the LLM."""
    parts = []
    for f in diff_files:
        parts.append(f"File: {f['file_path']}\nPatch:\n{f['patch_text']}\n" + "-" * 45)
    return "\n".join(parts)


def _is_whitespace_or_comment_only(diff_files: list[dict]) -> bool:
    """
    Returns True if the changes in diff_files only consist of comments (starting with #)
    or empty/whitespace lines, or if there are no changes.
    """
    for f in diff_files:
        patch = f.get("patch_text", "")
        if not patch:
            continue
        for line in patch.splitlines():
            # We only look at added lines
            if line.startswith("+") and not line.startswith("+++"):
                content = line[1:].strip()
                if content and not content.startswith("#"):
                    return False
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def review_pr(diff_files: list[dict], use_tool_calling: bool = True, repo: str | None = None, token: str | None = None) -> dict:
    """
    Reviews a PR diff and returns a structured verdict dictionary.
    """
    try:
        requests.get(f"{OLLAMA_HOST}/", timeout=3)
    except requests.exceptions.RequestException:
        raise RuntimeError(
            f"Cannot connect to Ollama at {OLLAMA_HOST}. "
            "Ensure the Ollama service is running."
        )

    diff_text = format_diff(diff_files)

    # Fetch repository README.md to help model understand domain/purpose alignment
    repo_readme = ""
    if repo and token:
        try:
            from github_client import fetch_repo_readme
            raw_readme = fetch_repo_readme(repo, token)
            if raw_readme:
                repo_readme = raw_readme[:4000]
                print(f"   Fetched repository README ({len(repo_readme)} chars) for context validation.")
        except Exception as exc:
            print(f"[Warning] Error fetching repository README: {exc}")

    rag_context = ""
    if repo:
        print(f"-> Querying RAG context for repo: {repo}")
        raw_context = retrieve_related_context(diff_files, repo)
        if raw_context:
            budget = max(0, RAG_CONTEXT_CHAR_BUDGET - len(diff_text))
            if len(raw_context) > budget:
                raw_context = raw_context[:budget] + "\n\n[RAG context truncated]"
            rag_context = raw_context
            print(f"   RAG context retrieved ({len(rag_context)} chars).")
        else:
            print("   No RAG context retrieved.")

    if use_tool_calling:
        try:
            verdict = run_agentic_loop(diff_files, diff_text, rag_context, repo_readme)
        except Exception as exc:
            print(f"\n[Warning] Agentic loop failed: {exc}. Falling back to deterministic pipeline.")
            verdict = run_fallback_review(diff_files, diff_text, rag_context, repo_readme)
    else:
        verdict = run_fallback_review(diff_files, diff_text, rag_context, repo_readme)

    # Programmatic override/sanity check: if changes are comment/whitespace-only AND there are no findings, force APPROVE
    if _is_whitespace_or_comment_only(diff_files):
        if not verdict.get("security_flags"):
            verdict["decision"] = "APPROVE"

    return verdict


# ---------------------------------------------------------------------------
# Agentic tool-calling loop
# ---------------------------------------------------------------------------



_AGENTIC_SYSTEM_PROMPT = (
    "You are an autonomous PR-review agent.\n"
    "You MUST evaluate repository relevance, security findings, and code quality INDEPENDENTLY:\n"
    "\n"
    "--- 1. REPOSITORY RELEVANCE (DOMAIN ALIGNMENT) ---\n"
    "Evaluate whether the files/code in the PR match the domain, purpose, and language of the repository using the provided README.md and RAG context as reference.\n"
    "- If the PR introduces files/code completely unrelated to the repository's domain (e.g. adding Java Android calculator or medical images to a Python PR Review Agent), set 'relevance' to '❌ Out of Scope - <reasons>' and set 'decision' to 'REQUEST_CHANGES'. You MUST use one of these exact observations in the 'reason' field:\n"
    "  * 'The proposed changes appear to be outside the intended scope of this repository.'\n"
    "  * 'This Pull Request introduces functionality unrelated to the project\\'s primary purpose.'\n"
    "  * 'Although the implementation may be technically correct, it does not align with the repository\\'s architecture or objectives.'\n"
    "- If the PR changes are relevant, set 'relevance' to '✅ Relevant' or '⚠️ Partially Relevant'. Do NOT let a code quality issue or security warning make you mark a relevant PR as out-of-scope. They are evaluated independently.\n"
    "\n"
    "--- 2. NO HALLUCINATION GUARANTEE (STRICT CRITICAL RULE) ---\n"
    "NEVER MAKE UP OR HALLUCINATE filenames, functions, line numbers, or vulnerabilities. Every file, function, line number, and vulnerability mentioned in your verdict MUST be directly present in the provided PR diff or Ruff/Bandit outputs. Do not invent any security flags or SQL injections if they are not explicitly detected in the inputs. If no security warnings or bugs exist in the provided inputs, set 'security_flags' to [] and do not mention any vulnerabilities. If evidence is insufficient to declare a bug, state that explicitly instead of fabricating details.\n"
    "\n"
    "--- 3. DECISION RULE ---\n"
    "- If a PR contains only minor, non-functional changes (e.g. whitespace changes, formatting, inline comment edits, documentation, README modifications) AND has no Ruff/Bandit warnings/errors, you MUST set 'decision' to 'APPROVE' (never 'COMMENT_ONLY' or 'REQUEST_CHANGES').\n"
    "- If the PR has functional code with no errors or security issues, set 'decision' to 'APPROVE'.\n"
    "- If there are minor styling issues, suggestions, or non-blocking queries, set 'decision' to 'COMMENT_ONLY'.\n"
    "- If there are critical bugs, linting errors, or security vulnerabilities (e.g. hardcoded credentials), set 'decision' to 'REQUEST_CHANGES'.\n"
    "\n"
    "When done, output ONLY a JSON object matching this exact schema:\n"
    f"{VERDICT_SCHEMA_HINT}\n"
    "Do not include any text outside the JSON object."
)


_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "run_lint",
            "description": "Runs the ruff linter on a changed Python file. Only call for .py files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path of the .py file to lint."}
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_security_scan",
            "description": "Runs the bandit security scanner on a changed Python file. Only call for .py files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path of the .py file to scan."}
                },
                "required": ["file_path"],
            },
        },
    },
]

_TOOL_FUNCTIONS = {"run_lint": run_lint, "run_security_scan": run_security_scan}


def _execute_tool_call(tool_call: dict) -> dict:
    """Dispatches a single tool call and returns the tool response message."""
    fn_name = tool_call.get("function", {}).get("name")
    fn_args = tool_call.get("function", {}).get("arguments", {})

    if isinstance(fn_args, str):
        try:
            fn_args = json.loads(fn_args)
        except Exception:
            fn_args = {}

    if fn_name in _TOOL_FUNCTIONS:
        file_path = fn_args.get("file_path", "")
        print(f"-> Agent called {fn_name}({file_path!r})")
        result = _TOOL_FUNCTIONS[fn_name](file_path)
        print(f"   Result preview: {result.strip()[:80]!r}...")
    else:
        result = f"Error: unknown tool '{fn_name}'."

    msg = {"role": "tool", "content": result, "name": fn_name}
    if "id" in tool_call:
        msg["tool_call_id"] = tool_call["id"]
    return msg


def run_agentic_loop(diff_files: list[dict], diff_text: str, rag_context: str = "", repo_readme: str = "") -> dict:
    """
    Runs an iterative agentic loop allowing the LLM to call tools before rendering a verdict.

    The loop continues until the model stops issuing tool calls (indicating a final answer)
    or until ``max_iterations`` is reached.
    """
    user_content = f"Please review this PR diff:\n\n{diff_text}"
    if repo_readme:
        user_content += f"\n\nRepository Description / README.md content:\n{repo_readme}"
    if rag_context:
        user_content += f"\n\nRelevant existing code from the repository:\n{rag_context}"

    messages = [
        {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    max_iterations = 6
    for _ in range(max_iterations):
        resp = requests.post(
            OLLAMA_CHAT_URL,
            json={"model": LLM_MODEL, "messages": messages, "tools": _TOOL_DEFINITIONS, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()

        message = resp.json().get("message", {})
        assistant_msg: dict = {"role": "assistant", "content": message.get("content", "")}
        if "tool_calls" in message:
            assistant_msg["tool_calls"] = message["tool_calls"]
        messages.append(assistant_msg)

        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            for tool_call in tool_calls:
                messages.append(_execute_tool_call(tool_call))
        else:
            return parse_and_validate_verdict(message.get("content", ""), messages)

    raise RuntimeError("Agentic loop reached maximum iterations without producing a verdict.")


# ---------------------------------------------------------------------------
# Fallback deterministic pipeline
# ---------------------------------------------------------------------------

def run_fallback_review(diff_files: list[dict], diff_text: str, rag_context: str = "", repo_readme: str = "") -> dict:
    """
    Deterministic fallback: runs ruff and bandit on every changed Python file,
    then submits everything to the LLM in a single prompt with JSON mode enabled.
    """
    print("-> [Fallback] Running ruff and bandit on all changed Python files...")

    lint_sections = []
    security_sections = []
    for f in diff_files:
        path = f["file_path"]
        if not path.endswith(".py"):
            continue
        print(f"   ruff: {path}")
        lint_sections.append(f"=== Ruff ({path}) ===\n{run_lint(path)}")
        print(f"   bandit: {path}")
        security_sections.append(f"=== Bandit ({path}) ===\n{run_security_scan(path)}")

    combined_lint = "\n\n".join(lint_sections) or "No Python files modified."
    combined_security = "\n\n".join(security_sections) or "No Python files modified."

    user_parts = [
        "You have been given the PR diff, ruff lint output, and bandit security output.",
        "Analyse all three and produce a structured review verdict.",
    ]
    if repo_readme:
        user_parts.append(f"\n=== REPOSITORY README / PURPOSE ===\n{repo_readme}")
    if rag_context:
        user_parts.append(f"\n=== RELATED CODE CONTEXT ===\n{rag_context}")
    user_parts += [
        f"\n=== PR DIFF ===\n{diff_text}",
        f"\n=== RUFF LINT ===\n{combined_lint}",
        f"\n=== BANDIT SECURITY ===\n{combined_security}",
        f"\nRespond ONLY with a JSON object matching this schema:\n{VERDICT_SCHEMA_HINT}"
    ]
    user_content = "\n".join(user_parts)

    resp = requests.post(
        OLLAMA_CHAT_URL,
        json={
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": _AGENTIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "format": "json",
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "")
    return parse_and_validate_verdict(content, [])


# ---------------------------------------------------------------------------
# Verdict parsing and validation
# ---------------------------------------------------------------------------

def parse_and_validate_verdict(content: str, messages: list, _retry: bool = False) -> dict:
    """
    Parses the LLM's response as a review verdict JSON object.

    If parsing fails on the first attempt, retries once by sending the schema
    back to the model with ``format: json`` enabled.

    Args:
        content:  Raw text returned by the LLM.
        messages: Conversation history (used for the retry prompt).
        _retry:   Internal flag — do not set manually.

    Returns:
        Validated dict with keys: ``decision``, ``reason``, ``summary``, ``security_flags``.

    Raises:
        ValueError: If parsing and validation fail even after the retry.
    """
    cleaned = content.strip()

    # Strip optional markdown code fences.
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

    try:
        data = json.loads(cleaned)

        missing = {"decision", "reason", "summary", "security_flags", "relevance"} - data.keys()
        if missing:
            if not _retry:
                raise ValueError(f"Missing required keys: {missing}")
            else:
                for k in ["decision", "reason", "summary", "security_flags"]:
                    if k not in data:
                        raise ValueError(f"Crucial key missing: {k}")
                data["relevance"] = data.get("relevance", "✅ Relevant")

        if data["decision"] not in VALID_DECISIONS:
            raise ValueError(f"Invalid decision value: {data['decision']!r}")

        if not isinstance(data["security_flags"], list):
            raise ValueError("'security_flags' must be a list.")

        return data

    except Exception as exc:
        if _retry:
            raise ValueError(
                f"Verdict validation failed after retry.\nError: {exc}\nRaw content: {content}"
            )

        print(f"[Warning] Failed to parse verdict: {exc}. Retrying with schema reinforcement...")

        retry_resp = requests.post(
            OLLAMA_CHAT_URL,
            json={
                "model": LLM_MODEL,
                "messages": messages + [{
                    "role": "user",
                    "content": (
                        "Your previous response was not valid JSON or was missing required keys.\n"
                        f"Respond ONLY with a JSON object matching this schema:\n{VERDICT_SCHEMA_HINT}"
                    ),
                }],
                "format": "json",
                "stream": False,
            },
            timeout=60,
        )
        retry_resp.raise_for_status()
        retry_content = retry_resp.json().get("message", {}).get("content", "")
        return parse_and_validate_verdict(retry_content, messages, _retry=True)
