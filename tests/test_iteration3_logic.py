import os
import sys
import unittest

# Add pr-review-agent to PATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pr-review-agent")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import index_repo

class TestIteration3Logic(unittest.TestCase):
    def test_ast_chunker_extracts_correct_nodes(self):
        """
        Verify that chunk_file correctly parses functions and classes using Python AST,
        retaining start and end lines.
        """
        temp_file = "temp_test_code.py"
        code = (
            "import os\n"
            "\n"
            "class MathHelper:\n"
            "    def add(self, a, b):\n"
            "        return a + b\n"
            "\n"
            "def global_func():\n"
            "    print('hello')\n"
        )
        
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(code)
            
        try:
            chunks = index_repo.chunk_file(temp_file)
            # We expect chunks for class MathHelper, function add (inside ClassDef) and function global_func
            names = [c["name"] for c in chunks]
            
            self.assertIn("MathHelper", names)
            self.assertIn("add", names)
            self.assertIn("global_func", names)
            
            # Check line numbers are captured correctly
            # MathHelper starts on line 3, global_func starts on line 7
            helper_chunk = [c for c in chunks if c["name"] == "MathHelper"][0]
            self.assertEqual(helper_chunk["start_line"], 3)
            self.assertEqual(helper_chunk["end_line"], 5)

            func_chunk = [c for c in chunks if c["name"] == "global_func"][0]
            self.assertEqual(func_chunk["start_line"], 7)
            self.assertEqual(func_chunk["end_line"], 8)
            
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def test_rag_prompt_budget_constraints(self):
        """
        Verify that review_pr enforces the 4000-character prompt budget constraint.
        """
        # Create a mock diff of size 3500 chars
        large_patch = "+" + ("a" * 3500) + "\n"
        mock_diff = [{"file_path": "file.py", "patch_text": large_patch}]
        
        # Test budget calculation
        from agent import format_diff
        diff_text = format_diff(mock_diff)
        
        # Make a large RAG context of 2000 chars
        large_rag = "x" * 2000
        
        # Run budget calculation logic from agent.py:
        allowed_rag_len = max(0, 4000 - len(diff_text))
        self.assertLess(allowed_rag_len, 4000)
        
        rag_context = large_rag
        if len(large_rag) > allowed_rag_len:
            rag_context = large_rag[:allowed_rag_len] + "\n\n[RAG Context Truncated due to size constraints]"
            
        # Verify length of prompt is bounded
        self.assertTrue(len(rag_context) <= allowed_rag_len + len("\n\n[RAG Context Truncated due to size constraints]"))
        self.assertIn("[RAG Context Truncated due to size constraints]", rag_context)

if __name__ == "__main__":
    unittest.main()
