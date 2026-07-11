import pytest
from unittest.mock import patch, MagicMock
from github_client import fetch_pr_diff, get_pr_head_sha, post_pr_comment

@patch("requests.get")
def test_fetch_pr_diff_success(mock_get):
    """
    Verify fetch_pr_diff returns expected file list with patches.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"filename": "app.py", "patch": "+++ new changes"},
        {"filename": "utils.py", "patch": "a" * 5000}  # Will trigger truncation
    ]
    mock_get.return_value = mock_resp

    files = fetch_pr_diff("owner/repo", 1, "test_token")
    
    assert len(files) == 2
    assert files[0]["file_path"] == "app.py"
    assert files[0]["patch_text"] == "+++ new changes"
    assert files[1]["file_path"] == "utils.py"
    # Second file patch should be truncated and end with truncation message
    assert "[Diff truncated due to size limit]" in files[1]["patch_text"]

@patch("requests.get")
def test_fetch_pr_diff_unauthorized(mock_get):
    """
    Verify fetch_pr_diff raises PermissionError on 401.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_get.return_value = mock_resp

    with pytest.raises(PermissionError) as exc:
        fetch_pr_diff("owner/repo", 1, "invalid_token")
    assert "Unauthorized" in str(exc.value)

@patch("requests.get")
def test_fetch_pr_diff_not_found(mock_get):
    """
    Verify fetch_pr_diff raises FileNotFoundError on 404.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_get.return_value = mock_resp

    with pytest.raises(FileNotFoundError) as exc:
        fetch_pr_diff("owner/repo", 9999, "test_token")
    assert "GitHub PR not found" in str(exc.value)

@patch("requests.get")
def test_get_pr_head_sha(mock_get):
    """
    Verify get_pr_head_sha correctly extracts SHA.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "head": {"sha": "abc123commitsha"}
    }
    mock_get.return_value = mock_resp

    sha = get_pr_head_sha("owner/repo", 1, "test_token")
    assert sha == "abc123commitsha"

@patch("requests.post")
def test_post_pr_comment_success(mock_post):
    """
    Verify post_pr_comment issues correct request.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_post.return_value = mock_resp

    # Should not raise exception
    post_pr_comment("owner/repo", 1, "test review comment", "test_token")
    mock_post.assert_called_once()
