# Developer Testing Utilities

This directory contains standalone scripts for batch-testing pull request review events without using live GitHub webhook triggers. All test results are persisted to the database and displayed with a `[TEST]` tag on the production Streamlit dashboard.

> [!NOTE]
> This folder is entirely self-contained. It can be safely deleted at any time without affecting the core application (agent, database, or dashboard).

---

## 1. Batch Review Test (`batch_review_test.py`)
This script processes multiple pull requests on a repository, runs the local review agent, and saves the output to the database under `source='batch_test'`.

### Run Command
Run the script using the virtual environment python interpreter from the project root:
```bash
.\pr-review-agent\venv\Scripts\python.exe dev-testing/batch_review_test.py --repo "owner/repo" --prs 1 2 3
```

---

## 2. Database Cleanup (`cleanup_test_data.py`)
This script cleans up test-generated rows from the database. It will only target rows where the `source` column is explicitly set to `'batch_test'`.

### Run Command
* **Dry Run** (only lists rows that would be deleted):
  ```bash
  .\pr-review-agent\venv\Scripts\python.exe dev-testing/cleanup_test_data.py
  ```
* **Actual Deletion**:
  ```bash
  .\pr-review-agent\venv\Scripts\python.exe dev-testing/cleanup_test_data.py --confirm
  ```

---

## Secrets & Configurations Hygiene
* All credentials, including the `GITHUB_TOKEN` (PAT) and `API_URL`, are loaded dynamically from your root `.env` file via `python-dotenv`.
* No passwords, tokens, or private values are hardcoded in these scripts.
