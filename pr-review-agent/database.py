import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

# Load environment variables from the .env file in the workspace
# We specify the path search up to the parent directory to find it at the workspace root
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    # Fallback to SQLite in-memory during test runs if no database is specified
    if os.environ.get("TESTING") == "true" or os.environ.get("PYTEST_CURRENT_TEST"):
        DATABASE_URL = "sqlite:///:memory:"
    else:
        DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/pr_review_db"

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
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
