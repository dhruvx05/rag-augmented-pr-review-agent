import os
import sys
from unittest.mock import patch, Mock
import requests

# Add source directory and project root to path for IDE import resolution
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pr-review-agent")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ruff: noqa: E402
from models import Review
from dashboard import fetch_pr_status

def test_archive_reviews_endpoints(client):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from sqlalchemy.orm import sessionmaker
    from database import Base

    # Create isolated SQLite memory database with StaticPool to keep the connection/tables alive
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Create tables
    Base.metadata.create_all(bind=engine)
    
    test_db = TestingSessionLocal()
    try:
        with patch("database.SessionLocal", return_value=test_db):
            # 1. Seed test database with reviews
            review1 = Review(
                repo="owner/repo", pr_number=1, commit_sha="sha111",
                decision="APPROVE", reason="lgtm", summary="summary 1", relevance="✅ Relevant", source="manual",
                archived=False
            )
            review2 = Review(
                repo="owner/repo", pr_number=2, commit_sha="sha222",
                decision="COMMENT_ONLY", reason="some notes", summary="summary 2", relevance="✅ Relevant", source="manual",
                archived=False
            )
            test_db.add(review1)
            test_db.add(review2)
            test_db.commit()

            # Verify seed
            assert test_db.query(Review).count() == 2

            # 2. Get reviews from FastAPI GET /reviews (default include_archived=False)
            resp = client.get("/reviews")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert data[0]["archived"] is False
            assert data[1]["archived"] is False

            # 3. Archive review 1 via POST /reviews/archive
            r1_id = data[0]["id"]
            archive_resp = client.post("/reviews/archive", json={"ids": [r1_id]})
            assert archive_resp.status_code == 200
            assert archive_resp.json()["archived_count"] == 1

            # 4. Fetch reviews again without include_archived -> should hide the archived review
            resp_hidden = client.get("/reviews")
            assert resp_hidden.status_code == 200
            data_hidden = resp_hidden.json()
            assert len(data_hidden) == 1
            assert data_hidden[0]["id"] != r1_id

            # 5. Fetch reviews with include_archived=true -> should show both
            resp_all = client.get("/reviews?include_archived=true")
            assert resp_all.status_code == 200
            data_all = resp_all.json()
            assert len(data_all) == 2
            # One of them must be archived
            archived_flags = [r["archived"] for r in data_all]
            assert True in archived_flags
            assert False in archived_flags
    finally:
        test_db.close()
        Base.metadata.drop_all(bind=engine)


@patch("requests.get")
def test_fetch_pr_status_success_cases(mock_get):
    # Mock Merged PR response
    mock_resp_merged = Mock()
    mock_resp_merged.status_code = 200
    mock_resp_merged.json.return_value = {"state": "closed", "merged": True}
    
    mock_get.return_value = mock_resp_merged
    res = fetch_pr_status("owner/repo", 42, "mock-token")
    assert res == "merged"

    # Mock Closed PR response (not merged)
    mock_resp_closed = Mock()
    mock_resp_closed.status_code = 200
    mock_resp_closed.json.return_value = {"state": "closed", "merged": False}
    
    mock_get.return_value = mock_resp_closed
    res = fetch_pr_status("owner/repo", 43, "mock-token")
    assert res == "closed"

    # Mock Open PR response
    mock_resp_open = Mock()
    mock_resp_open.status_code = 200
    mock_resp_open.json.return_value = {"state": "open", "merged": False}
    
    mock_get.return_value = mock_resp_open
    res = fetch_pr_status("owner/repo", 44, "mock-token")
    assert res == "open"


@patch("requests.get")
def test_fetch_pr_status_graceful_failures(mock_get):
    # Mock HTTP error (e.g. rate limit 403 or unauthorized)
    mock_resp_fail = Mock()
    mock_resp_fail.status_code = 403
    
    mock_get.return_value = mock_resp_fail
    res = fetch_pr_status("owner/repo", 45, "mock-token")
    assert res == "unknown"

    # Mock raising exception (e.g. timeout)
    mock_get.side_effect = requests.exceptions.Timeout()
    res = fetch_pr_status("owner/repo", 46, "mock-token")
    assert res == "unknown"
