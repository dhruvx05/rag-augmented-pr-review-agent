import pytest
from unittest.mock import patch, MagicMock
from agent import parse_and_validate_verdict

def test_parse_and_validate_verdict_success():
    """
    Verify parse_and_validate_verdict correctly parses and returns valid JSON.
    """
    raw_content = """
    ```json
    {
      "decision": "APPROVE",
      "relevance": "✅ Relevant",
      "summary": "This is a summary.",
      "reason": "This is the reasoning details.",
      "security_flags": []
    }
    ```
    """
    result = parse_and_validate_verdict(raw_content, [])
    assert result["decision"] == "APPROVE"
    assert result["relevance"] == "✅ Relevant"
    assert result["summary"] == "This is a summary."
    assert result["reason"] == "This is the reasoning details."
    assert result["security_flags"] == []

def test_parse_and_validate_verdict_invalid_schema():
    """
    Verify parse_and_validate_verdict raises ValueError on missing keys or invalid decision value.
    """
    # Missing decision key
    raw_content_missing_key = '{"summary": "test", "reason": "test"}'
    with pytest.raises(ValueError) as exc:
        parse_and_validate_verdict(raw_content_missing_key, [], _retry=True)
    assert "Crucial key missing" in str(exc.value)

    # Invalid decision value
    raw_content_invalid_val = '{"decision": "STUB", "relevance": "✅ Relevant", "summary": "test", "reason": "test", "security_flags": []}'
    with pytest.raises(ValueError) as exc:
        parse_and_validate_verdict(raw_content_invalid_val, [], _retry=True)
    assert "Invalid decision" in str(exc.value)

    # security_flags is not a list
    raw_content_invalid_type = '{"decision": "APPROVE", "relevance": "✅ Relevant", "summary": "test", "reason": "test", "security_flags": "not a list"}'
    with pytest.raises(ValueError) as exc:
        parse_and_validate_verdict(raw_content_invalid_type, [], _retry=True)
    assert "'security_flags' must be a list" in str(exc.value)

@patch("requests.post")
def test_parse_and_validate_verdict_retry_path(mock_post):
    """
    Verify parse_and_validate_verdict retries with schema correction on malformed JSON.
    """
    # First call yields malformed JSON (missing braces), but mock POST returns valid JSON on retry
    malformed_initial = '{"decision": "COMMENT_ONLY", "reason": "incomplete"'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "content": '{"decision": "COMMENT_ONLY", "relevance": "✅ Relevant", "summary": "retried", "reason": "now valid", "security_flags": []}'
        }
    }
    mock_post.return_value = mock_response

    messages = [{"role": "user", "content": "original prompt"}]
    result = parse_and_validate_verdict(malformed_initial, messages)
    
    # Assert retry API was invoked once
    mock_post.assert_called_once()
    assert result["decision"] == "COMMENT_ONLY"
    assert result["summary"] == "retried"
    assert result["reason"] == "now valid"
    assert result["security_flags"] == []


@patch("agent.requests.post")
@patch("agent.requests.get")
@patch("github_client.fetch_repo_readme")
def test_review_pr_context_validation_relevance(mock_fetch_readme, mock_get, mock_post):
    """
    Verify review_pr successfully passes the repository README for context validation.
    """
    mock_fetch_readme.return_value = "This repository is a Python PR Review Agent that runs ruff and bandit."
    
    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get.return_value = mock_get_response

    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "message": {
            "content": '{"decision": "REQUEST_CHANGES", "relevance": "❌ Out of Scope - Adds an Android Calculator app", "summary": "Out of scope changes added.", "reason": "The proposed changes appear to be outside the intended scope of this repository.", "security_flags": []}'
        }
    }
    mock_post.return_value = mock_post_response

    diff_files = [{"file_path": "MainActivity.java", "patch_text": "+ public class MainActivity extends Activity {}"}]
    
    # Import review_pr inside to ensure patched version is tested
    from agent import review_pr
    verdict = review_pr(diff_files, use_tool_calling=False, repo="my-org/my-repo", token="my-token")
    
    assert verdict["decision"] == "REQUEST_CHANGES"
    assert "Out of Scope" in verdict["relevance"]
    assert "outside the intended scope of this repository" in verdict["reason"]
    mock_fetch_readme.assert_called_once_with("my-org/my-repo", "my-token")


@patch("agent.requests.post")
@patch("agent.requests.get")
@patch("github_client.fetch_repo_readme")
def test_whitespace_comment_only_verdict_approve(mock_fetch_readme, mock_get, mock_post):
    """
    Verify that a whitespace or comment-only change with no linter/security issues
    correctly resolves to APPROVE.
    """
    mock_fetch_readme.return_value = "A simple python project."
    
    mock_get_response = MagicMock()
    mock_get_response.status_code = 200
    mock_get.return_value = mock_get_response

    # Even if LLM returns COMMENT_ONLY, the programmatic override should force APPROVE
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post_response.json.return_value = {
        "message": {
            "content": '{"decision": "COMMENT_ONLY", "relevance": "✅ Relevant", "summary": "Comment only change.", "reason": "Minor comment update.", "security_flags": []}'
        }
    }
    mock_post.return_value = mock_post_response

    diff_files = [{"file_path": "main.py", "patch_text": "+ # just a comment"}]
    
    from agent import review_pr
    verdict = review_pr(diff_files, use_tool_calling=False, repo="my-org/my-repo", token="my-token")
    
    assert verdict["decision"] == "APPROVE"
    assert verdict["security_flags"] == []
