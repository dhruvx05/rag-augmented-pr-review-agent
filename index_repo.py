import os
import sys
import ast
import uuid
import argparse
import requests
from dotenv import load_dotenv

# Load workspace .env settings
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

class PythonASTChunker(ast.NodeVisitor):
    """
    Parses Python code into clean AST chunks for functions and classes.
    """
    def __init__(self, source_code: str, file_path: str):
        self.source_code = source_code
        self.file_path = file_path
        self.lines = source_code.splitlines()
        self.chunks = []

    def visit_FunctionDef(self, node):
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        # Reconstruct block content
        content = "\n".join(self.lines[start-1:end])
        self.chunks.append({
            "name": node.name,
            "type": "function",
            "start_line": start,
            "end_line": end,
            "content": content
        })
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        content = "\n".join(self.lines[start-1:end])
        self.chunks.append({
            "name": node.name,
            "type": "class",
            "start_line": start,
            "end_line": end,
            "content": content
        })
        self.generic_visit(node)

def chunk_file(file_path: str) -> list[dict]:
    """
    Reads a file and returns semantic chunks. If parsing fails, fall back to entire file.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        print(f"Skipping {file_path}: Unable to read file ({e})")
        return []

    if not code.strip():
        return []

    # If it is not a python file, chunk by standard text blocks or return the whole file
    if not file_path.endswith(".py"):
        # Non-python files are chunked as a single file block
        return [{
            "name": "module",
            "type": "file",
            "start_line": 1,
            "end_line": len(code.splitlines()),
            "content": code
        }]

    try:
        tree = ast.parse(code)
        chunker = PythonASTChunker(code, file_path)
        chunker.visit(tree)
        
        # If no function or class definitions were found, return the whole file as a chunk
        if not chunker.chunks:
            return [{
                "name": "module",
                "type": "file",
                "start_line": 1,
                "end_line": len(code.splitlines()),
                "content": code
            }]
            
        return chunker.chunks
    except Exception as e:
        # Fall back to whole file if AST parsing fails (e.g. syntax error in testing/draft code)
        print(f"[Warning] AST parse failed for {file_path} ({e}). Falling back to whole-file chunking.")
        return [{
            "name": "module",
            "type": "file",
            "start_line": 1,
            "end_line": len(code.splitlines()),
            "content": code
        }]

def get_embedding(text: str, ollama_host: str) -> list[float]:
    """
    Fetches the vector embedding representation from Ollama's nomic-embed-text model.
    """
    url = f"{ollama_host}/api/embeddings"
    payload = {
        "model": "nomic-embed-text",
        "prompt": text
    }
    response = requests.post(url, json=payload, timeout=20)
    if response.status_code == 404 or response.status_code == 400:
        raise RuntimeError(
            "Model 'nomic-embed-text' not found or unsupported in Ollama.\n"
            "Please run 'ollama pull nomic-embed-text' on your host first."
        )
    response.raise_for_status()
    return response.json()["embedding"]

def init_qdrant_collection(qdrant_url: str, collection: str):
    """
    Ensures that the collection exists in Qdrant with the correct configurations.
    """
    check_url = f"{qdrant_url}/collections/{collection}"
    resp = requests.get(check_url, timeout=5)
    if resp.status_code == 200:
        print(f"Collection '{collection}' already exists in Qdrant.")
        return

    print(f"Creating Qdrant collection '{collection}'...")
    create_body = {
        "vectors": {
            "size": 768, # nomic-embed-text vector dimensions
            "distance": "Cosine"
        }
    }
    create_resp = requests.put(check_url, json=create_body, timeout=5)
    create_resp.raise_for_status()
    print(f"Collection '{collection}' created successfully.")

def upsert_chunks_to_qdrant(qdrant_url: str, collection: str, points: list[dict]):
    """
    Upserts a batch of point vectors and payloads into Qdrant.
    """
    url = f"{qdrant_url}/collections/{collection}/points"
    payload = {"points": points}
    resp = requests.put(url, json=payload, timeout=10)
    resp.raise_for_status()

def main():
    parser = argparse.ArgumentParser(description="Semantically index repository files into Qdrant.")
    parser.add_argument("--repo-path", required=True, help="Absolute path to the target repository folder")
    parser.add_argument("--repo-name", help="Repository full name identifier (e.g. owner/repo). Defaults to directory name.")
    parser.add_argument("--collection", default="pr_reviews", help="Qdrant collection name")
    parser.add_argument("--qdrant-url", help="Qdrant REST API URL. Reads from environment or defaults to localhost.")
    parser.add_argument("--ollama-host", help="Ollama Host URL. Reads from environment or defaults to localhost.")
    
    args = parser.parse_args()
    
    # 1. Establish configurations
    repo_path = os.path.abspath(args.repo_path)
    if not os.path.isdir(repo_path):
        print(f"[Error] Repository directory '{repo_path}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    repo_name = args.repo_name or os.path.basename(repo_path)
    qdrant_url = args.qdrant_url or os.environ.get("QDRANT_URL", "http://localhost:6333")
    ollama_host = args.ollama_host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    print(f"Indexing repository:  {repo_path}")
    print(f"Identifier tag name:  {repo_name}")
    print(f"Qdrant target URL:    {qdrant_url}")
    print(f"Ollama host URL:      {ollama_host}")
    print("-" * 50)

    # 2. Check Qdrant liveness
    try:
        requests.get(f"{qdrant_url}/collections", timeout=5)
    except Exception as e:
        print(f"[Error] Failed to connect to Qdrant REST API at {qdrant_url}: {e}", file=sys.stderr)
        print("Please check that the Qdrant service is running and accessible.", file=sys.stderr)
        sys.exit(1)

    # 3. Check Ollama model liveness
    try:
        # Fast query to ensure nomic-embed-text is running
        get_embedding("test", ollama_host)
    except Exception as e:
        print(f"[Error] Failed to embed test string: {e}", file=sys.stderr)
        print("Please check that Ollama is running and has 'nomic-embed-text' pulled.", file=sys.stderr)
        sys.exit(1)

    # 4. Initialize collection
    try:
        init_qdrant_collection(qdrant_url, args.collection)
    except Exception as e:
        print(f"[Error] Failed to initialize Qdrant collection: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. Walk repo and gather chunks
    all_chunks = []
    for root, dirs, files in os.walk(repo_path):
        # Skip version control, virtual environments and caches
        dirs[:] = [d for d in dirs if d not in [".git", "venv", ".venv", "__pycache__", ".gemini"]]
        for f in files:
            # We index python files and other configuration text files
            if f.endswith((".py", ".md", ".txt", ".json", "Dockerfile")):
                full_path = os.path.join(root, f)
                rel_path = os.path.relpath(full_path, repo_path).replace("\\", "/")
                
                # Retrieve chunks for this file
                chunks = chunk_file(full_path)
                for chunk in chunks:
                    chunk["rel_path"] = rel_path
                    all_chunks.append(chunk)

    print(f"Found {len(all_chunks)} semantic chunks to embed. Generating vectors...")

    # 6. Generate embeddings and upload in batches
    points = []
    batch_size = 20
    processed_count = 0

    for chunk in all_chunks:
        try:
            # Create a nice context representation for embedding: include file path and name to reinforce context
            embed_prompt = f"File: {chunk['rel_path']}\nEntity: {chunk['name']}\nContent:\n{chunk['content']}"
            vector = get_embedding(embed_prompt, ollama_host)
            
            point = {
                "id": str(uuid.uuid4()),
                "vector": vector,
                "payload": {
                    "file_path": chunk["rel_path"],
                    "function_name": chunk["name"],
                    "start_line": chunk["start_line"],
                    "end_line": chunk["end_line"],
                    "content": chunk["content"],
                    "repo": repo_name
                }
            }
            points.append(point)
            
            # Upsert in batches
            if len(points) >= batch_size:
                upsert_chunks_to_qdrant(qdrant_url, args.collection, points)
                processed_count += len(points)
                print(f"   Indexed {processed_count}/{len(all_chunks)} chunks...")
                points = []
                
        except Exception as e:
            print(f"[Warning] Failed to index chunk '{chunk['name']}' in {chunk['rel_path']}: {e}")

    # Upsert remaining points
    if points:
        try:
            upsert_chunks_to_qdrant(qdrant_url, args.collection, points)
            processed_count += len(points)
            print(f"   Indexed {processed_count}/{len(all_chunks)} chunks...")
        except Exception as e:
            print(f"[Warning] Failed to upload final points batch: {e}")

    print("-" * 50)
    print(f"INDEXING COMPLETE! Successfully indexed {processed_count} semantic code chunks.")
    print("NOTE: This indexing represents a full repository rewrite. Incremental re-indexing on push is a future enhancement.")

if __name__ == "__main__":
    main()
