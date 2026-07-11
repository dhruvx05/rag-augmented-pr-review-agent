import os
import importlib.util
from models import Review
from unittest.mock import patch

# Dynamically import run_cleanup due to the hyphen in 'dev-testing' directory name
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
spec = importlib.util.spec_from_file_location(
    "cleanup_test_data",
    os.path.join(parent_dir, "dev-testing", "cleanup_test_data.py")
)
cleanup_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup_module)
run_cleanup = cleanup_module.run_cleanup

def test_source_column_default_and_cleanup(test_db):
    """
    Verify the source column default value and that the cleanup script
    only deletes 'batch_test' rows, leaving 'webhook' rows intact.
    """
    # 1. Insert a review with default source (should fall back to webhook)
    r1 = Review(
        repo="owner/repo",
        pr_number=1,
        commit_sha="sha1",
        decision="APPROVE",
        reason="Looks good",
        summary="Summary"
    )
    test_db.add(r1)
    test_db.commit()
    
    # Assert default is webhook or None (depending on SQLite/SQLAlchemy lifecycle before commit/refresh)
    # Since we set server_default, the database assigns it upon insertion.
    test_db.refresh(r1)
    assert r1.source == "webhook"

    # 2. Insert a batch_test review
    r2 = Review(
        repo="owner/repo",
        pr_number=2,
        commit_sha="sha2",
        decision="COMMENT_ONLY",
        reason="Some suggestions",
        summary="Summary",
        source="batch_test"
    )
    test_db.add(r2)
    test_db.commit()
    
    # Assert database counts
    assert test_db.query(Review).count() == 2
    assert test_db.query(Review).filter_by(source="batch_test").count() == 1
    assert test_db.query(Review).filter_by(source="webhook").count() == 1

    # 3. Run cleanup with confirm=False (Dry Run)
    with patch.object(cleanup_module, "SessionLocal", return_value=test_db):
        run_cleanup(confirm=False)
    
    # Verify no rows were deleted in dry run
    assert test_db.query(Review).count() == 2

    # 4. Run cleanup with confirm=True
    with patch.object(cleanup_module, "SessionLocal", return_value=test_db):
        run_cleanup(confirm=True)

    # Verify only batch_test row was deleted, and webhook row remains
    assert test_db.query(Review).count() == 1
    remaining = test_db.query(Review).first()
    assert remaining.pr_number == 1
    assert remaining.source == "webhook"
