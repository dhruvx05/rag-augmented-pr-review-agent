# ruff: noqa: E402
import os
import sys

# Insert the parent directory and the pr-review-agent directory into sys.path
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, "pr-review-agent"))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(parent_dir, ".env"))

import argparse
from database import SessionLocal
from models import Review

def run_cleanup(confirm: bool):
    db = SessionLocal()
    try:
        # Find rows with source = 'batch_test'
        query = db.query(Review).filter(Review.source == "batch_test")
        count = query.count()
        
        if count == 0:
            print("No test data (source='batch_test') found in the database. Nothing to clean up.")
            return

        print(f"Found {count} row(s) with source='batch_test':")
        rows = query.all()
        for idx, row in enumerate(rows, start=1):
            print(f"  [{idx}] Repo: {row.repo} | PR: #{row.pr_number} | Commit: {row.commit_sha[:7]} | Verdict: {row.decision}")

        if not confirm:
            print("\n*** DRY RUN MODE ***")
            print("To actually delete these rows, re-run the script with the '--confirm' flag:")
            print("  python dev-testing/cleanup_test_data.py --confirm")
        else:
            print(f"\nDeleting {count} row(s) from the reviews table...")
            query.delete(synchronize_session=False)
            db.commit()
            print("Test data deleted successfully.")
            
    except Exception as e:
        db.rollback()
        print(f"Error occurred during cleanup: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up batch test data from the reviews database.")
    parser.add_argument("--confirm", action="store_true", help="Explicitly confirm the deletion of test data.")
    args = parser.parse_args()

    run_cleanup(args.confirm)
