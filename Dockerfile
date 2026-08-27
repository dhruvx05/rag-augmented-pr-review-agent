FROM python:3.11-slim

# Prevent python from writing pyc files to disk and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies needed for building psycopg2 and running ruff check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*


# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code into container
COPY pr-review-agent/ /app/pr-review-agent/
COPY dashboard.py /app/
COPY index_repo.py /app/
COPY start.sh /app/

RUN chmod +x /app/start.sh

WORKDIR /app

EXPOSE 8000 8501

CMD ["/app/start.sh"]
