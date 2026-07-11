# ruff: noqa: E402
import os
import sys

# Insert the parent directory and the pr-review-agent directory into sys.path
# so we can import models, database, agent, and github_client directly.
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, parent_dir)
sys.path.insert(0, os.path.join(parent_dir, "pr-review-agent"))

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(parent_dir, ".env"))

import argparse
from database import SessionLocal
from models import Review
from agent import review_pr
from github_client import fetch_pr_diff, get_pr_head_sha
from sqlalchemy.exc import IntegrityError

def run_batch_test(repo: str, prs: list[int]):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("Error: GITHUB_TOKEN environment variable is not set. Please configure it in your .env file.")
        sys.exit(1)

    print(f"Starting batch review test for repo '{repo}' on PRs {prs}...")
    db = SessionLocal()
    try:
        for pr_num in prs:
            print(f"\nProcessing PR #{pr_num}...")
            try:
                commit_sha = get_pr_head_sha(repo, pr_num, token)
            except Exception as e:
                print(f"Failed to fetch metadata for PR #{pr_num}: {e}")
                continue

            # Check if already reviewed (idempotency check)
            existing = db.query(Review).filter_by(repo=repo, pr_number=pr_num, commit_sha=commit_sha).first()
            if existing:
                print(f"PR #{pr_num} at commit {commit_sha[:7]} is already reviewed in the DB. Skipping.")
                continue

            print(f"Fetching diff for PR #{pr_num}...")
            try:
                diff_files = fetch_pr_diff(repo, pr_num, token)
            except Exception as e:
                print(f"Failed to fetch diff: {e}")
                continue

            if not diff_files:
                print(f"PR #{pr_num} has empty diff. Saving APPROVE...")
                try:
                    db.add(Review(
                        repo=repo, pr_number=pr_num, commit_sha=commit_sha,
                        decision="APPROVE", reason="Empty diff - batch test", summary="Empty diff",
                        relevance="✅ Relevant", source="batch_test"
                    ))
                    db.commit()
                    print(f"Successfully recorded empty PR #{pr_num}.")
                except IntegrityError:
                    db.rollback()
                continue

            print("Generating review...")
            try:
                verdict = review_pr(diff_files, use_tool_calling=True, repo=repo, token=token)
            except Exception as e:
                print(f"Failed to generate review: {e}")
                continue

            print(f"Persisting verdict: {verdict.get('decision')}...")
            try:
                db.add(Review(
                    repo=repo, pr_number=pr_num, commit_sha=commit_sha,
                    decision=verdict.get("decision", "COMMENT_ONLY"),
                    reason=verdict.get("reason", ""),
                    summary=verdict.get("summary", ""),
                    relevance=verdict.get("relevance", "✅ Relevant"),
                    source="batch_test"
                ))
                db.commit()
                print(f"Successfully recorded review for PR #{pr_num}.")
            except IntegrityError:
                db.rollback()
                print(f"Concurrent insert detected for PR #{pr_num} commit {commit_sha[:7]}. Skipped.")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batch review testing on pull requests.")
    parser.add_argument("--repo", required=True, help="GitHub repository in 'owner/repo' format.")
    parser.add_argument("--prs", required=True, nargs="+", type=int, help="List of PR numbers to review.")
    args = parser.parse_args()

    run_batch_test(args.repo, args.prs)
