import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint, Boolean
from database import Base

class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    repo = Column(String, nullable=False, index=True)
    pr_number = Column(Integer, nullable=False)
    commit_sha = Column(String, nullable=False, index=True)
    decision = Column(String, nullable=False, index=True)
    reason = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    relevance = Column(Text, nullable=True)
    source = Column(String, nullable=True, server_default="webhook")
    archived = Column(Boolean, nullable=True, server_default="false", index=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True)

    # Enforce database unique constraint on (repo, pr_number, commit_sha)
    # This prevents duplicate review submissions in parallel or subsequent trigger events.
    __table_args__ = (
        UniqueConstraint("repo", "pr_number", "commit_sha", name="uq_repo_pr_commit"),
    )
