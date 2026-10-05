"""GET /jobs — Phase 6, chunk 0b: replaces the Phase 1 mock stub with a
real query against JobPosting (Phase 4's real ingested table, ~424 rows
from RemoteOK + Arbeitnow) and a real per-user match score.

Match score is deliberately simple: keyword overlap between the user's
active resume and each posting's title+description, using the same
tokenizer the ATS check (resume_pdf.py) already uses. This phase's actual
job is the frontend, not a ranking model — "real instead of fake" is the
bar, not "sophisticated." JobPosting's own docstring already names this
exact design: scoring is a query-time concern, not something ingestion
could ever compute (no user in the loop during a scheduled bulk run).

Cache-aside dropped from this version — per-user match scores mean the
cache key would have to be per-user too, and at this data size (~424 rows)
the query itself is cheap enough that a per-user cache isn't worth the
added invalidation complexity yet. Revisit if/when the table is much
bigger.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, Query

from jobpilot_shared.db import get_session
from jobpilot_shared.models import JobPosting, Resume, User
from jobpilot_shared.text_matching import extract_keywords

from app.deps import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _match_score(resume_keywords: set[str], posting: JobPosting) -> float:
    if not resume_keywords:
        return 0.0
    posting_keywords = extract_keywords(f"{posting.title} {posting.description}")
    if not posting_keywords:
        return 0.0
    overlap = resume_keywords & posting_keywords
    # Normalized against the posting's own keyword count, not the
    # resume's — a short posting that's entirely covered by the resume
    # should score high even if the resume has plenty of unrelated
    # keywords (prior jobs, skills this posting doesn't ask for at all).
    return round(len(overlap) / len(posting_keywords), 4)


@router.get("")
async def list_jobs(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(
        select(Resume).where(Resume.user_id == user.id, Resume.is_active.is_(True))
    )
    resume = result.scalars().first()
    resume_keywords = extract_keywords(resume.content) if resume else set()

    total = (await session.execute(select(JobPosting))).scalars().all()
    scored = [
        {
            "id": str(posting.id),
            "title": posting.title,
            "company": posting.company,
            "location": posting.location,
            "is_remote": posting.is_remote,
            "url": posting.url,
            "description": posting.description,
            "tags": posting.tags,
            "salary_min": posting.salary_min,
            "salary_max": posting.salary_max,
            "match_score": _match_score(resume_keywords, posting),
        }
        for posting in total
    ]
    scored.sort(key=lambda job: job["match_score"], reverse=True)

    return {
        "jobs": scored[offset : offset + limit],
        "total": len(scored),
        "has_resume": resume is not None,
    }
