import os
from unittest.mock import patch, MagicMock
from agent import _call_llm_api, _get_query_embedding, run_agentic_loop
from app import load_demo_reviews_fixture

def test_demo_reviews_fixture_loading():
    """
    Verify load_demo_reviews_fixture correctly loads 3 pre-recorded reviews.
    """
    reviews = load_demo_reviews_fixture()
    assert isinstance(reviews, list)
    assert len(reviews) == 3
    decisions = {r["decision"] for r in reviews}
    assert "APPROVE" in decisions
    assert "REQUEST_CHANGES" in decisions
    assert "COMMENT_ONLY" in decisions

@patch.dict(os.environ, {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "mock_groq_key"})
@patch("requests.post")
def test_groq_llm_dispatch_format(mock_post):
    """
    Verify _call_llm_api formats payload correctly for Groq OpenAI-compatible endpoint.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"decision": "APPROVE", "relevance": "✅ Relevant", "summary": "Groq test", "reason": "Groq reason", "security_flags": []}'
                }
            }
        ]
    }
    mock_post.return_value = mock_response

    messages = [{"role": "user", "content": "Test prompt"}]
    msg, content = _call_llm_api(messages, json_mode=True)

    assert msg["role"] == "assistant"
    assert "Groq test" in content

    # Verify post URL and headers
    called_url = mock_post.call_args[0][0]
    called_headers = mock_post.call_args[1]["headers"]
    assert "api.groq.com" in called_url
    assert called_headers["Authorization"] == "Bearer mock_groq_key"

@patch.dict(os.environ, {"EMBEDDING_PROVIDER": "jina", "JINA_API_KEY": "mock_jina_key"})
@patch("requests.post")
def test_jina_embedding_dispatch(mock_post):
    """
    Verify _get_query_embedding formats payload correctly for Jina AI endpoint.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }
    mock_post.return_value = mock_response

    vec = _get_query_embedding("def hello(): pass")
    assert vec == [0.1, 0.2, 0.3]

    called_url = mock_post.call_args[0][0]
    called_headers = mock_post.call_args[1]["headers"]
    assert "api.jina.ai" in called_url
    assert called_headers["Authorization"] == "Bearer mock_jina_key"

@patch("agent._call_llm_api")
@patch("agent.run_fallback_review")
def test_react_loop_duplicate_tool_call_fallback(mock_fallback, mock_call_llm):
    """
    Verify ReAct tool-calling loop breaks and triggers fallback review if LLM emits duplicate tool call.
    """
    mock_call_llm.return_value = (
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "run_lint", "arguments": '{"file_path": "main.py"}'}}
            ]
        },
        ""
    )
    mock_fallback.return_value = {
        "decision": "APPROVE",
        "relevance": "✅ Relevant",
        "summary": "Fallback triggered",
        "reason": "Duplicate tool call intercepted",
        "security_flags": []
    }

    diff_files = [{"file_path": "main.py", "patch_text": "+ print('hello')"}]
    verdict = run_agentic_loop(diff_files, "+ print('hello')")

    assert mock_fallback.called
    assert verdict["summary"] == "Fallback triggered"
