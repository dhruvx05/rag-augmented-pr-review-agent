import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

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

# NOTE: Column migrations (relevance, source, archived) are handled exclusively
# in app.py's lifespan startup hook, where a verified DB connection is guaranteed.

def get_db():
    """
    FastAPI dependency that provides a clean database session context per request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
