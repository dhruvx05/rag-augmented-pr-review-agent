from unittest.mock import patch, MagicMock
import requests
from agent import review_pr

@patch("requests.post")
@patch("requests.get")
def test_review_pr_qdrant_offline_fallback(mock_get, mock_post):
    """
    Verify review_pr succeeds with non-RAG review when Qdrant is unreachable.
    """
    # 1. Setup mock responses
    # Ollama liveness check succeeds, but Qdrant check raises ConnectionError
    def selective_get(url, *args, **kwargs):
        if "11434" in url:
            resp = MagicMock()
            resp.status_code = 200
            return resp
        raise requests.exceptions.ConnectionError("Connection refused")
    mock_get.side_effect = selective_get

    # Mock post selectively to return dummy embedding for embedding requests, and verdict JSON for chat requests
    def selective_post(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "embeddings" in url:
            resp.json.return_value = {"embedding": [0.1] * 768}
        else:
            resp.json.return_value = {
                "message": {
                    "content": '{"decision": "APPROVE", "relevance": "✅ Relevant", "summary": "offline test", "reason": "went fine", "security_flags": []}'
                }
            }
        return resp
    mock_post.side_effect = selective_post

    # Input mock diff files
    diff_files = [{"file_path": "main.py", "patch_text": "+++"}]

    # We expect review_pr to complete without throwing an exception
    # note: use_tool_calling=False to test fallback review or use_tool_calling=True which calls run_agentic_loop
    verdict = review_pr(diff_files, use_tool_calling=False, repo="owner/repo")

    assert verdict["decision"] == "APPROVE"
    assert verdict["summary"] == "offline test"
    assert verdict["reason"] == "went fine"
    assert verdict["security_flags"] == []
    
    # Assert get was attempted to check Qdrant liveness
    qdrant_check_call = any(
        "collections/pr_reviews" in call[0][0] for call in mock_get.call_args_list
    )
    assert qdrant_check_call, "Qdrant collection liveness check was not called."
