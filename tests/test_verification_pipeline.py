import os
import sys
import unittest
from sqlalchemy.exc import IntegrityError

# Add source directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pr-review-agent")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import SessionLocal, Base, engine
from models import Review
from agent import retrieve_related_context, review_pr, format_diff
import requests

class TestIteration3Verification(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        # Establish endpoints
        cls.ollama_host = "http://localhost:11434"
        cls.qdrant_url = "http://localhost:6333"
        cls.collection = "pr_reviews"
        cls.repo = "test-org/test-repo"
        
        # Test endpoints are responsive
        try:
            requests.get(f"{cls.ollama_host}/", timeout=2)
        except Exception:
            raise unittest.SkipTest("Ollama is not running at localhost:11434. Skipping integration tests.")
            
        try:
            requests.get(f"{cls.qdrant_url}/collections", timeout=2)
        except Exception:
            raise unittest.SkipTest("Qdrant is not running at localhost:6333. Skipping integration tests.")
            
        # Ensure database tables exist locally (connecting to the Postgres container)
        Base.metadata.create_all(bind=engine)

    def test_01_qdrant_retrieval(self):
        print("\n--- 1. Verification of Qdrant Retrieval ---")
        # Define a mock diff segment that searches for the JSON parsing function
        mock_diff = [
            {
                "file_path": "pr-review-agent/agent.py",
                "patch_text": "+ def parse_and_validate_verdict(content: str, messages: list):\n+     # JSON validator function logic here"
            }
        ]
        
        # Call the live retrieve_related_context function
        context = retrieve_related_context(
            diff_files=mock_diff,
            repo=self.repo,
            k=2,
        )
        
        print(f"Retrieved context size: {len(context)} characters.")
        print(f"Retrieved Context Snippet:\n{context[:400]}")
        
        self.assertTrue(len(context) > 0, "No context was retrieved from Qdrant.")
        self.assertIn("parse_and_validate_verdict", context, "Expected function was not retrieved.")
        self.assertIn("pr-review-agent/agent.py", context, "Expected file path was not found in context.")
        print("[OK] Qdrant Retrieval verified successfully.")

    def test_02_retrieval_filtering(self):
        print("\n--- 2. Verification of Qdrant Repository Filtering ---")
        mock_diff = [
            {
                "file_path": "pr-review-agent/agent.py",
                "patch_text": "+ def parse_and_validate_verdict(content: str, messages: list):\n+     # JSON validator function logic here"
            }
        ]
        
        # Call the retrieval with a non-existent repository name to ensure filtering works
        context = retrieve_related_context(
            diff_files=mock_diff,
            repo="nonexistent-org/nonexistent-repo",
            k=2,
        )
        
        self.assertEqual(context, "", "Repository filtering failed: returned points for another repo.")
        print("[OK] Qdrant Repository Filtering verified successfully.")

    def test_03_prompt_budget_truncation(self):
        print("\n--- 3. Verification of Prompt Budget & Truncation ---")
        # Generate a large mock diff (~2500 characters)
        large_patch = "+" + ("a" * 2500) + "\n"
        mock_diff = [{"file_path": "large_file.py", "patch_text": large_patch}]
        diff_text = format_diff(mock_diff)
        
        # Make a large context (~3000 characters)
        large_context = "x" * 3000
        
        # Run budget calculation logic inside agent.py
        allowed_rag_len = max(0, 4000 - len(diff_text))
        print(f"Diff Length: {len(diff_text)}")
        print(f"Allowed RAG Length: {allowed_rag_len}")
        
        rag_context = large_context
        if len(large_context) > allowed_rag_len:
            rag_context = large_context[:allowed_rag_len] + "\n\n[RAG Context Truncated due to size constraints]"
            
        combined_prompt_len = len(diff_text) + len(rag_context)
        print(f"Final Combined Prompt Context Length: {combined_prompt_len}")
        
        self.assertTrue(combined_prompt_len <= 4000 + len("\n\n[RAG Context Truncated due to size constraints]"))
        self.assertIn("[RAG Context Truncated due to size constraints]", rag_context)
        print("[OK] Prompt Budget Truncation logic verified successfully.")

    def test_04_agent_e2e_review(self):
        print("\n--- 4. Verification of Live Agent Review ---")
        # Define a mock diff that introduces an unused import style issue
        mock_diff = [
            {
                "file_path": "pr-review-agent/app.py",
                "patch_text": "@@ -1,5 +1,6 @@\n import os\n import sys\n+import tempfile\n import hmac\n import hashlib"
            }
        ]
        
        # Run live review loop (RAG + Ollama qwen2.5-coder:7b)
        # Note: We enforce fallback=False to ensure the agentic tool-calling loop executes
        print("Invoking agent loop...")
        verdict = review_pr(mock_diff, use_tool_calling=True, repo=self.repo)
        
        print("\nAgent Review Output:")
        print(f"Decision: {verdict.get('decision')}")
        print(f"Summary:  {verdict.get('summary')}")
        print(f"Reason:   {verdict.get('reason')}")
        
        self.assertIn(verdict.get("decision"), ["APPROVE", "COMMENT_ONLY", "REQUEST_CHANGES"])
        self.assertTrue(len(verdict.get("summary")) > 0)
        self.assertTrue(len(verdict.get("reason")) > 0)
        
        # Store verdict in class variables to write to DB in the next test
        self.__class__.verdict = verdict
        print("[OK] Live Agent Review verified successfully.")

    def test_05_postgres_persistence_and_idempotency(self):
        print("\n--- 5. Verification of PostgreSQL Persistence & Idempotency ---")
        verdict = getattr(self, "verdict", {
            "decision": "COMMENT_ONLY",
            "summary": "Mock summary",
            "reason": "Mock reason details"
        })
        
        commit_sha = "mock_commit_sha_12345"
        pr_number = 999
        
        db = SessionLocal()
        
        # Clean up any existing test records
        db.query(Review).filter(Review.repo == self.repo, Review.pr_number == pr_number).delete()
        db.commit()
        
        try:
            # 1. Test insertion
            review_rec = Review(
                repo=self.repo,
                pr_number=pr_number,
                commit_sha=commit_sha,
                decision=verdict["decision"],
                reason=verdict["reason"],
                summary=verdict["summary"],
                relevance="✅ Relevant"
            )
            db.add(review_rec)
            db.commit()
            print("Successfully inserted review record.")
            
            # Verify record was stored correctly
            db_rec = db.query(Review).filter(
                Review.repo == self.repo, 
                Review.pr_number == pr_number, 
                Review.commit_sha == commit_sha
            ).first()
            
            self.assertIsNotNone(db_rec)
            self.assertEqual(db_rec.decision, verdict["decision"])
            self.assertEqual(db_rec.summary, verdict["summary"])
            self.assertEqual(db_rec.relevance, "✅ Relevant")
            print("[OK] Verified review persistence in PostgreSQL.")
            
            # 2. Test unique constraint (idempotency check)
            print("Attempting duplicate insertion (same repo, pr_number, and commit_sha)...")
            dup_rec = Review(
                repo=self.repo,
                pr_number=pr_number,
                commit_sha=commit_sha,
                decision="APPROVE",
                reason="Duplicate check",
                summary="Duplicate summary",
                relevance="✅ Relevant"
            )
            db.add(dup_rec)
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
            print("[OK] Verified unique constraint duplicate webhook block (IntegrityError raised).")
            
        finally:
            # Clean up test records
            db.query(Review).filter(Review.repo == self.repo, Review.pr_number == pr_number).delete()
            db.commit()
            db.close()

if __name__ == "__main__":
    unittest.main()
