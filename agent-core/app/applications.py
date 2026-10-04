"""Shared Application row lookup/creation.

Both /prepare and /interview need "the Application row for this user+job"
to exist before they can persist anything onto it — pulled out here rather
than duplicated, since chunk 9 (wiring /prepare's own outputs into
Application) will need the exact same lookup.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.models import Application


async def get_or_create_application(
    session: AsyncSession, user_id: uuid.UUID, job_posting_id: str
) -> Application:
    result = await session.execute(
        select(Application).where(
            Application.user_id == user_id, Application.job_posting_id == job_posting_id
        )
    )
    application = result.scalar_one_or_none()
    if application is None:
        application = Application(user_id=user_id, job_posting_id=job_posting_id)
        session.add(application)
        await session.commit()
        await session.refresh(application)
    return application
