import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv
import logging

# Load environment variables from the .env file in the workspace
# We specify the path search up to the parent directory to find it at the workspace root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    # We fallback to SQLite locally if no database is specified during tests,
    # but the production/compose service requires Postgres
    DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/pr_review_db"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

logger = logging.getLogger(__name__)

# Perform inline migration for reviews relevance and source columns if DB table already exists
try:
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if inspector.has_table("reviews"):
        columns = [c["name"] for c in inspector.get_columns("reviews")]
        if "relevance" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN relevance TEXT"))
        if "source" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE reviews ADD COLUMN source TEXT DEFAULT 'webhook'"))
except Exception as exc:
    # Log the exception so that CI security checks (bandit) don't flag bare except-pass
    # and so maintainers can see why the inline migration check failed in environments
    # where the database is not available at import time.
    logger.warning(f"Database inline-migration check failed at import time: {exc}")


def get_db():
    """
    FastAPI dependency that provides a clean database session context per request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
