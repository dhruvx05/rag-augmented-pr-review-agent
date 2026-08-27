#!/bin/bash
set -e

echo "========================================================"
echo "🤖 Starting PR Review Agent Multi-Service Container..."
echo "========================================================"

PORT=${PORT:-8501}
API_PORT=${API_PORT:-8000}

# 1. Start FastAPI backend service in background
echo "-> Launching FastAPI Backend Service on port ${API_PORT}..."
cd /app/pr-review-agent
python -m uvicorn app:app --host 0.0.0.0 --port ${API_PORT} &
BACKEND_PID=$!

# Wait briefly for FastAPI server to initialize
sleep 4

# 2. Launch Streamlit Dashboard UI in foreground
echo "-> Launching Streamlit Portal Dashboard on port ${PORT}..."
cd /app
export API_URL=http://127.0.0.1:${API_PORT}

exec python -m streamlit run dashboard.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
