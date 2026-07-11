import requests

def fetch_pr_diff(repo: str, pr_number: int, token: str) -> list[dict]:
    """
    Fetches the pull request files and patches from the GitHub REST API.
    
    Args:
        repo: Repository name in 'owner/repo' format.
        pr_number: Pull request ID.
        token: GitHub Personal Access Token (PAT).
        
    Returns:
        A list of dicts, each with keys 'file_path' and 'patch_text'.
        
    Raises:
        ValueError: If parameters are invalid.
        PermissionError: If the token is invalid, expired, or doesn't have repository access.
        FileNotFoundError: If the repository or PR does not exist.
        RuntimeError: If a general network error or unexpected API error occurs.
    """
    if not token or not token.strip():
        raise ValueError("GitHub Personal Access Token (PAT) is missing or empty.")

    if "/" not in repo or len(repo.split("/")) != 2:
        raise ValueError(f"Invalid repository format '{repo}'. Expected 'owner/repo'.")

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-Review-Agent/0.1"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 401:
            raise PermissionError("GitHub API request failed: Unauthorized (invalid or expired token).")
        elif response.status_code == 403:
            error_msg = response.json().get("message", "")
            raise PermissionError(f"GitHub API request forbidden: {error_msg}. Check your token permissions/rate limits.")
        elif response.status_code == 404:
            raise FileNotFoundError(f"GitHub PR not found: repo '{repo}', PR #{pr_number}. Check if they exist.")
        
        response.raise_for_status()
        
        files_data = response.json()
        result = []
        for file_info in files_data:
            file_path = file_info.get("filename", "")
            patch_text = file_info.get("patch", "") or ""
            
            # Truncate diff text past ~4000 characters with a note appended
            max_len = 4000
            if len(patch_text) > max_len:
                patch_text = patch_text[:max_len] + "\n\n... [Diff truncated due to size limit] ...\n"
            
            result.append({
                "file_path": file_path,
                "patch_text": patch_text
            })
        return result

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error communicating with GitHub API: {e}")

def get_pr_head_sha(repo: str, pr_number: int, token: str) -> str:
    """
    Fetches the head commit SHA of the pull request to verify file state during review.
    
    Args:
        repo: Repository name in 'owner/repo' format.
        pr_number: Pull request ID.
        token: GitHub Personal Access Token (PAT).
        
    Returns:
        The head commit SHA string.
        
    Raises:
        ValueError, PermissionError, FileNotFoundError, RuntimeError.
    """
    if not token or not token.strip():
        raise ValueError("GitHub Personal Access Token (PAT) is missing or empty.")

    if "/" not in repo or len(repo.split("/")) != 2:
        raise ValueError(f"Invalid repository format '{repo}'. Expected 'owner/repo'.")

    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-Review-Agent/0.1"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 401:
            raise PermissionError("GitHub API request failed: Unauthorized (invalid or expired token).")
        elif response.status_code == 403:
            error_msg = response.json().get("message", "")
            raise PermissionError(f"GitHub API request forbidden: {error_msg}.")
        elif response.status_code == 404:
            raise FileNotFoundError(f"GitHub PR not found: repo '{repo}', PR #{pr_number}.")
            
        response.raise_for_status()
        pr_data = response.json()
        return pr_data.get("head", {}).get("sha", "")
        
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error communicating with GitHub API: {e}")

def post_pr_comment(repo: str, pr_number: int, comment: str, token: str) -> None:
    """
    Posts a comment to the specified pull request.
    
    Args:
        repo: Repository name in 'owner/repo' format.
        pr_number: Pull request ID.
        comment: The text content of the comment to post.
        token: GitHub Personal Access Token (PAT).
    """
    if not token or not token.strip():
        raise ValueError("GitHub Personal Access Token (PAT) is missing or empty.")

    if "/" not in repo or len(repo.split("/")) != 2:
        raise ValueError(f"Invalid repository format '{repo}'. Expected 'owner/repo'.")

    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-Review-Agent/0.1"
    }
    payload = {"body": comment}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        
        if response.status_code == 401:
            raise PermissionError("GitHub API request failed: Unauthorized (invalid or expired token).")
        elif response.status_code == 403:
            error_msg = response.json().get("message", "")
            raise PermissionError(f"GitHub API request forbidden: {error_msg}.")
        elif response.status_code == 404:
            raise FileNotFoundError(f"GitHub PR/Issue not found: repo '{repo}', PR #{pr_number}.")
            
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error posting PR comment: {e}")


def fetch_open_prs(repo: str, token: str) -> list[dict]:
    """
    Fetches open pull requests for the repository from the GitHub API.
    """
    if not token or not token.strip():
        raise ValueError("GitHub Personal Access Token (PAT) is missing.")

    if "/" not in repo or len(repo.split("/")) != 2:
        raise ValueError(f"Invalid repository format '{repo}'. Expected 'owner/repo'.")

    url = f"https://api.github.com/repos/{repo}/pulls?state=open"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-Review-Agent/1.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 401:
            raise PermissionError("GitHub API request failed: Unauthorized (invalid token).")
        elif response.status_code == 404:
            raise FileNotFoundError(f"GitHub repository '{repo}' not found.")
        response.raise_for_status()
        
        prs = response.json()
        result = []
        for pr in prs:
            result.append({
                "number": pr.get("number"),
                "title": pr.get("title"),
                "user": pr.get("user", {}).get("login"),
                "state": pr.get("state"),
                "html_url": pr.get("html_url"),
                "head_sha": pr.get("head", {}).get("sha"),
            })
        return result
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to fetch open PRs: {e}")





def fetch_repo_readme(repo: str, token: str) -> str:
    """
    Fetches the README.md file content of the repository from the GitHub API.
    """
    if not token or not token.strip():
        return ""
    if "/" not in repo or len(repo.split("/")) != 2:
        return ""

    url = f"https://api.github.com/repos/{repo}/readme"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Accept": "application/vnd.github.raw",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-Review-Agent/1.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.text
    except Exception as exc:
        print(f"[Warning] Failed to fetch repository README: {exc}")
    return ""

