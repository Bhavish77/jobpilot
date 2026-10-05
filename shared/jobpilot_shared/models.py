"""Postgres schema — users, resumes, applications.

Relational, transactional, needs joins and ACID: an application's status
shouldn't be eventually consistent (design doc, "why two databases, not
one"). Raw job postings and event logs live in Mongo instead — see mongo.py.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    """Login is email+password or Google — either works for any job seeker,
    not just developers (design doc, "Auth model"). Exactly one of
    `password_hash`/`google_id` is set depending on how the account was
    created; a user can have both if they registered with a password and
    later signed in with Google using the same email (linked by email in the
    Google callback, not enforced at the DB level).

    `github_id`/`github_username` are populated later and optionally, via
    `/auth/github/connect` from the profile screen — purely to grant Phase 3's
    RAG ingestion read access to the user's repos. GitHub is never required
    to use JobPilot."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)

    github_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    github_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Phase 10 fields land here later: plan, key_mode. Kept out of v1 on
    # purpose — the design doc explicitly defers BYOK/plans past the core
    # product working.

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    resumes: Mapped[list["Resume"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Resume(Base):
    """A version of the user's resume/background. Read directly (no
    chunking/embedding) by the Resume Agent, the Cover Letter Agent, and
    Interview Prep's gap analysis — a single resume is too small to justify
    retrieval (see docs/PHASE_3_PLAN.md). Only `is_active=True` is ever
    read; uploading a new one deactivates the previous one."""

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="resumes")


class JobPosting(Base):
    """A real job posting ingested from a public job board (Phase 4) —
    replaces jobs.py's mock data. One row per (source, external_id); a
    daily re-run upserts on that pair rather than duplicating rows, since
    postings persist across days until the listing expires or disappears.

    Deliberately no per-user match score here — scoring a posting against
    a *specific* user's resume needs that user's resume, which doesn't
    exist during a scheduled bulk ingestion run with no user in the loop.
    That's a query-time concern (whenever /jobs is actually called by a
    logged-in user), not something ingestion can meaningfully compute.
    """

    __tablename__ = "job_postings"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(32), index=True)  # "remoteok" | "arbeitnow"
    external_id: Mapped[str] = mapped_column(String(255))  # the source's own id/slug for this posting

    title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_remote: Mapped[bool] = mapped_column(default=False)
    url: Mapped[str] = mapped_column(String(1024))
    description: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    salary_min: Mapped[int | None] = mapped_column(nullable=True)
    salary_max: Mapped[int | None] = mapped_column(nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationStatus(str, enum.Enum):
    """Mirrors the Pipeline board columns in the UI mockup exactly —
    Discover has nothing to do with this table; a row only exists here once
    the user hits 'Prepare'."""

    PREPARING = "preparing"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"
    INTERVIEWING = "interviewing"


class Application(Base):
    """One job a user has started the pipeline for. Job postings themselves
    (raw + scored) live in Mongo/Postgres per Phase 4 — this table only
    exists once 'Prepare' has been clicked for a specific job posting id."""

    __tablename__ = "applications"
    __table_args__ = (
        # A user can only have one in-flight application per job posting —
        # this is the row-level guard behind "double-click can't create two
        # applications" (paired with the optimistic-locking version check
        # below at the point of concurrent update, not just at insert).
        UniqueConstraint("user_id", "job_posting_id", name="uq_user_job"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str] = mapped_column(String(255), index=True)  # Mongo/normalized-Postgres job id, Phase 4

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="application_status"), default=ApplicationStatus.PREPARING
    )
    resume_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Interview Prep's study curriculum (Phase 2, chunk 5b) — real gaps
    # between the candidate's profile resume and this JD, not the tailored
    # per-job resume_output above.
    interview_curriculum: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optimistic-locking version check (design doc, resilience patterns) —
    # a concurrent status update must read this, then write it back +1 in
    # the same WHERE clause, or the update is rejected as stale.
    version: Mapped[int] = mapped_column(default=1)

    # Phase 6 polish: the Celery task_id from the most recent /prepare
    # call. Without this, /prepare/status had no way to distinguish "the
    # pipeline is still genuinely running" from "the task died and
    # nothing will ever finish this" — a checkpoint stuck mid-pipeline
    # looks identical either way unless something checks the task's own
    # Celery result state, which needs the task_id to look up.
    last_prepare_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="applications")
