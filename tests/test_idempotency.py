import pytest
from sqlalchemy.exc import IntegrityError
from models import Review
from app import process_pr_review, _in_progress_commits
from unittest.mock import patch

def test_reviews_table_unique_constraint(test_db):
    """
    Verify PostgreSQL unique constraint on (repo, pr_number, commit_sha) is enforced.
    """
    # Create first review
    r1 = Review(
        repo="owner/repo",
        pr_number=1,
        commit_sha="sha123",
        decision="APPROVE",
        reason="looks good",
        summary="summary"
    )
    test_db.add(r1)
    test_db.commit()

    # Attempt to create duplicate review
    r2 = Review(
        repo="owner/repo",
        pr_number=1,
        commit_sha="sha123",
        decision="REQUEST_CHANGES",
        reason="style errors",
        summary="summary"
    )
    test_db.add(r2)
    with pytest.raises(IntegrityError):
        test_db.commit()
    test_db.rollback()

@patch("github_client.post_pr_comment")
@patch("agent.review_pr")
@patch("github_client.fetch_pr_diff")
def test_process_pr_review_aborts_on_duplicate_commit(mock_fetch_diff, mock_review_pr, mock_post_comment, test_db):
    """
    Verify process_pr_review catches IntegrityError and aborts duplicate comments.
    """
    repo = "owner/repo"
    pr_number = 1
    commit_sha = "sha123"
    token = "test_token"

    # Setup database with an existing record
    existing_review = Review(
        repo=repo,
        pr_number=pr_number,
        commit_sha=commit_sha,
        decision="APPROVE",
        reason="Reason",
        summary="Summary"
    )
    test_db.add(existing_review)
    test_db.commit()

    # Configure mocks to return valid review responses
    mock_fetch_diff.return_value = [{"file_path": "main.py", "patch_text": "+++"}]
    mock_review_pr.return_value = {
        "decision": "APPROVE",
        "summary": "Summary",
        "reason": "Reason",
        "security_flags": []
    }

    # Add commit to in progress tracker
    idempotency_key = (repo, pr_number, commit_sha)
    _in_progress_commits.add(idempotency_key)

    # Override get_db in the module namespace or patch database session
    with patch("database.SessionLocal", return_value=test_db):
        process_pr_review(repo, pr_number, commit_sha, token)

    # Since it is a duplicate, the background task should hit IntegrityError (or fetch early check)
    # and abort without posting comments to GitHub
    mock_post_comment.assert_not_called()
    
    # Assert key was removed from in-progress commits set
    assert idempotency_key not in _in_progress_commits
