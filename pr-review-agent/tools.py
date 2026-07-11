import subprocess  # nosec B404
import sys
import os
import tempfile

import requests

# Module-level context, populated once per background review task via configure_tools().
_repo: str | None = None
_token: str | None = None
_pr_number: int | None = None
_head_sha: str | None = None

_GITHUB_HEADERS_BASE = {
    "Accept": "application/vnd.github.v3.raw",
    "User-Agent": "PR-Review-Agent/1.0",
}


def configure_tools(repo: str, token: str, pr_number: int, head_sha: str | None = None) -> None:
    """
    Sets the repository context used by ``run_lint`` and ``run_security_scan``
    to fetch remote file contents from GitHub.

    Must be called before either tool function is invoked.
    """
    global _repo, _token, _pr_number, _head_sha
    _repo = repo
    _token = token
    _pr_number = pr_number
    _head_sha = head_sha


def _fetch_file_content(file_path: str) -> str | None:
    """
    Fetches file content from GitHub at the PR's head commit SHA.

    Returns:
        The file content as a string, or None if the file was deleted or fetch failed.
    """
    if not (_repo and _token and _head_sha):
        return None

    url = f"https://api.github.com/repos/{_repo}/contents/{file_path}?ref={_head_sha}"
    headers = {**_GITHUB_HEADERS_BASE, "Authorization": f"Bearer {_token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch {file_path} from GitHub: {exc}") from exc


def _run_subprocess(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """
    Runs a subprocess, falling back to the Python module form if the
    executable is not on PATH (e.g. inside a virtual environment).
    """
    try:
        return subprocess.run(cmd, **kwargs)  # nosec B603
    except FileNotFoundError:
        # Replace bare executable with 'python -m <tool>' using the current interpreter.
        module_cmd = [sys.executable, "-m", cmd[0]] + cmd[1:]
        return subprocess.run(module_cmd, **kwargs)  # nosec B603


def _check_prerequisites(file_path: str, tool_name: str) -> str | None:
    """
    Returns an error string if tool prerequisites are unmet, otherwise None.
    Shared validation used by both run_lint and run_security_scan.
    """
    if not file_path.endswith(".py"):
        return f"Skipped: {file_path!r} is not a Python file."
    if not (_repo and _token):
        return "Error: call configure_tools() before using analysis tools."
    if not _head_sha:
        return "Error: head commit SHA is unknown — cannot fetch file at a deterministic state."
    return None


def run_lint(file_path: str) -> str:
    """
    Downloads ``file_path`` from GitHub at the PR's head SHA and lints it with ruff.

    Returns:
        Ruff output string, or a descriptive error/skip message.
    """
    if (err := _check_prerequisites(file_path, "ruff")):
        return err

    try:
        content = _fetch_file_content(file_path)
    except RuntimeError as exc:
        return str(exc)

    if content is None:
        return f"Skipped: {file_path!r} was deleted or does not exist in this PR."

    try:
        result = _run_subprocess(
            ["ruff", "check", "-", "--stdin-filename", file_path],
            input=content,
            text=True,
            capture_output=True,
            timeout=10,
        )
        output = (result.stdout + result.stderr).strip()
        return output if output else f"No lint issues found in {file_path!r}."
    except Exception as exc:
        return f"Error running ruff on {file_path!r}: {exc}"


def run_security_scan(file_path: str) -> str:
    """
    Downloads ``file_path`` from GitHub at the PR's head SHA and scans it with bandit.

    Bandit requires a real file on disk, so the content is written to a temporary
    file and cleaned up after scanning.

    Returns:
        Bandit output string, or a descriptive error/skip message.
    """
    if (err := _check_prerequisites(file_path, "bandit")):
        return err

    try:
        content = _fetch_file_content(file_path)
    except RuntimeError as exc:
        return str(exc)

    if content is None:
        return f"Skipped: {file_path!r} was deleted or does not exist in this PR."

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(content)

        result = _run_subprocess(
            ["bandit", "-q", "-r", tmp_path],
            text=True,
            capture_output=True,
            timeout=15,
        )
        output = (result.stdout + result.stderr).replace(tmp_path, file_path).strip()
        return output if output else f"No security issues found in {file_path!r}."
    except Exception as exc:
        return f"Error running bandit on {file_path!r}: {exc}"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
