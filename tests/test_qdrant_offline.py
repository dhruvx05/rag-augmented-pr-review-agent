import os
import sys

# Add source directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pr-review-agent")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import review_pr

def main():
    print("--- Testing Agent Review with Qdrant Offline ---")
    mock_diff = [
        {
            "file_path": "pr-review-agent/app.py",
            "patch_text": "@@ -1,5 +1,6 @@\n import os\n import sys\n+import tempfile\n import hmac\n import hashlib"
        }
    ]
    
    # We expect a warning to be logged because Qdrant is offline
    print("Invoking review_pr...")
    try:
        verdict = review_pr(mock_diff, use_tool_calling=True, repo="test-org/test-repo")
        print("\nReview Succeeded!")
        print(f"Decision: {verdict.get('decision')}")
        print(f"Summary:  {verdict.get('summary')}")
        print(f"Reason:   {verdict.get('reason')}")
        assert verdict.get("decision") in ["APPROVE", "COMMENT_ONLY", "REQUEST_CHANGES"]
        print("\nFallback test: SUCCESS!")
    except Exception as e:
        print(f"\nFallback test: FAILED! Raised exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
