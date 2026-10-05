"""GET /applications/{job_posting_id}, POST /applications/{job_posting_id}/apply.

Phase 4, chunk 5: the optimistic-locking endpoint the `Application.version`
column (Phase 1) was added for. Prepare-only, no-auto-submit (CLAUDE.md)
means this endpoint never talks to any job board — the human applies
externally themselves, then tells JobPilot "I applied" so the Pipeline
card moves from Ready to apply -> Applied. Only that one transition exists
here; Applied -> Interviewing can reuse the same version-checked UPDATE
shape once there's a reason to add it.

GET exists so the client has a version to send back — same reasoning as
the rate limiter and the prepare_graph checkpointer: never let a client
guess at state it should be reading.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import String, cast, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.db import get_session
from jobpilot_shared.models import Application, ApplicationStatus, JobPosting, User

from app.deps import get_current_user

router = APIRouter(prefix="/applications", tags=["applications"])


class ApplyRequest(BaseModel):
    version: int


def _payload(application: Application) -> dict:
    return {
        "id": str(application.id),
        "status": application.status.value,
        "version": application.version,
    }


async def _get_application(session: AsyncSession, user_id, job_posting_id: str) -> Application:
    result = await session.execute(
        select(Application).where(
            Application.user_id == user_id, Application.job_posting_id == job_posting_id
        )
    )
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="No application found for this job")
    return application


@router.get("")
async def list_applications(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Left outer join: an Application's job_posting_id is a client-chosen
    # opaque string (it predates real JobPosting rows existing at all —
    # plenty of test data used made-up ids), so it isn't guaranteed to
    # match a real posting. Falls back to just the id when it doesn't.
    result = await session.execute(
        select(Application, JobPosting)
        .outerjoin(JobPosting, cast(JobPosting.id, String) == Application.job_posting_id)
        .where(Application.user_id == user.id)
        .order_by(Application.updated_at.desc())
    )
    applications = []
    for application, posting in result.all():
        applications.append(
            {
                **_payload(application),
                "jobPostingId": application.job_posting_id,
                "title": posting.title if posting else application.job_posting_id,
                "company": posting.company if posting else None,
            }
        )
    return {"applications": applications}


@router.get("/{job_posting_id}")
async def get_application(
    job_posting_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await _get_application(session, user.id, job_posting_id)
    return _payload(application)


@router.post("/{job_posting_id}/apply")
async def apply(
    job_posting_id: str,
    req: ApplyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    application = await _get_application(session, user.id, job_posting_id)

    if application.status != ApplicationStatus.READY_TO_APPLY:
        raise HTTPException(
            status_code=400,
            detail=f"Can only apply from 'ready_to_apply', current status is '{application.status.value}'",
        )

    # The actual optimistic lock: the WHERE clause requires the version the
    # client read to still be current. If another request already moved
    # this row (e.g. a double-click, or two tabs), rowcount comes back 0
    # instead of silently overwriting that other write.
    result = await session.execute(
        update(Application)
        .where(Application.id == application.id, Application.version == req.version)
        .values(status=ApplicationStatus.APPLIED, version=Application.version + 1)
    )
    if result.rowcount == 0:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Application was changed by another request — reload and retry with the latest version.",
        )

    await session.commit()
    await session.refresh(application)
    return _payload(application)
