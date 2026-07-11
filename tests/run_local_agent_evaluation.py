import os
import sys
import io
from unittest.mock import patch

# Set console output encoding to utf-8 to print emojis on Windows without crashing
if sys.platform.startswith("win"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add directories to system path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pr-review-agent")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent import review_pr

# 1. Define test cases representing the core edge cases
SCENARIOS = [
    {
        "name": "Scenario A: Out-of-Scope PR (Android Calculator Code)",
        "diff_files": [
            {
                "file_path": "app/src/main/java/com/calc/MainActivity.java",
                "patch_text": """+package com.calc;
+import android.app.Activity;
+import android.os.Bundle;
+
+public class MainActivity extends Activity {
+    @Override
+    protected void onCreate(Bundle savedInstanceState) {
+        super.onCreate(savedInstanceState);
+        setContentView(R.layout.activity_main);
+    }
+    
+    public int add(int a, int b) {
+        return a + b;
+    }
+}"""
            }
        ],
        "repo": "owner/pr-review-agent",
        "description": "Simulates adding a Java mobile application component to a Python-based CI/CD code review agent repository."
    },
    {
        "name": "Scenario B: Insignificant PR (Whitespace & Comment Only)",
        "diff_files": [
            {
                "file_path": "pr-review-agent/agent.py",
                "patch_text": """@@ -12,3 +12,4 @@
 # OLLAMA_HOST environment variable
 OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
+# Just adding a simple inline developer comment here
+
 """
            }
        ],
        "repo": "owner/pr-review-agent",
        "description": "Simulates a PR containing only a minor comment update and trailing whitespace, which has no functional effect."
    },
    {
        "name": "Scenario C: Relevant PR with Security Issue (Hardcoded Slack Token)",
        "diff_files": [
            {
                "file_path": "pr-review-agent/notifier.py",
                "patch_text": """+import requests
+
+def send_slack_notification(message):
+    # Post a message to our dev Slack channel
+    webhook_url = "PLACEHOLDER_MOCK_SLACK_WEBHOOK_URL"
+    token = "PLACEHOLDER_MOCK_SLACK_API_TOKEN"
+    requests.post(webhook_url, json={"text": message, "token": token})
+"""
            }
        ],
        "repo": "owner/pr-review-agent",
        "description": "Simulates a functional, relevant Python change that introduces critical security risks (hardcoded authentication token)."
    },
    {
        "name": "Scenario D: Relevant & Correct Python PR",
        "diff_files": [
            {
                "file_path": "pr-review-agent/utils.py",
                "patch_text": """+def format_duration(seconds: float) -> str:
+    \"\"\"Converts a duration in seconds into a human-readable string representation.\"\"\"
+    if seconds < 60:
+        return f"{seconds:.1f}s"
+    minutes = int(seconds // 60)
+    rem_seconds = seconds % 60
+    return f"{minutes}m {rem_seconds:.1f}s"
+"""
            }
        ],
        "repo": "owner/pr-review-agent",
        "description": "Simulates a valid, relevant helper function added to the repository's core utility package."
    }
]

# Mock repository README.md that describes a PR Review Agent
MOCK_README_CONTENT = """
# AI PR Review Agent
This repository contains a local-first automated code review assistant. 
It integrates Ruff for Python linting, Bandit for security auditing, and uses Qdrant for semantic RAG search to understand code contexts.
Features:
- On-demand trigger on Pull Request events
- Local LLM code reviews (qwen2.5-coder:7b)
- Static analysis & security scan tools
- Streamlit control panel portal
"""

def mock_lint_side_effect(file_path):
    return ""

def mock_security_side_effect(file_path):
    if "notifier.py" in file_path:
        return "[HIGH] pr-review-agent/notifier.py:5: B105:hardcoded_password_string - Potential security risk due to hardcoded Slack token."
    return ""

@patch("agent.run_lint", side_effect=mock_lint_side_effect)
@patch("agent.run_security_scan", side_effect=mock_security_side_effect)
@patch("github_client.fetch_repo_readme")
def run_evaluation(mock_readme, mock_security, mock_lint):
    mock_readme.return_value = MOCK_README_CONTENT

    print("=" * 80)
    print("           LOCAL AI AGENT RELEVANCE & EDGE CASE EVALUATION TEST")
    print("=" * 80)
    print("Using mock repository README.md describing the project as:")
    print("-" * 50)
    print(MOCK_README_CONTENT.strip())
    print("-" * 50)
    print("Connecting to local Ollama instance...\n")

    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"\n[{i}/{len(SCENARIOS)}] {scenario['name']}")
        print(f"Description: {scenario['description']}")
        print(f"Simulating review for repository: {scenario['repo']}")
        print("Running LLM analysis (this triggers the real local Ollama)...")
        
        try:
            # Trigger review_pr directly on the files
            # Note: We pass token="mock-token" so that the README fetching pathway is triggered
            verdict = review_pr(
                diff_files=scenario["diff_files"],
                use_tool_calling=False, # Use fallback deterministic pipeline for fast execution in test
                repo=scenario["repo"],
                token="mock-token"
            )
            
            print("\n>>> EVALUATION RESULT:")
            print(f"  * Verdict Decision : {verdict.get('decision')}")
            print(f"  * Relevance Label  : {verdict.get('relevance')}")
            print(f"  * Summary Phrase   : {verdict.get('summary')}")
            print(f"  * Warning/Reason   : {verdict.get('reason')}")
            print(f"  * Security Flags   : {verdict.get('security_flags')}")
            print("-" * 80)
            
        except Exception as exc:
            print(f"  ❌ Error during review execution: {exc}")
            print("-" * 80)

if __name__ == "__main__":
    run_evaluation()
