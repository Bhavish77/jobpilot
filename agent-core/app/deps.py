"""Shared FastAPI dependencies for agent-core."""

import jwt
from fastapi import Cookie, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from jobpilot_shared.auth import decode_session_jwt
from jobpilot_shared.db import get_session
from jobpilot_shared.models import User

SESSION_COOKIE_NAME = "jobpilot_session"


async def get_current_user(
    jobpilot_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not jobpilot_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
    try:
        user_id = decode_session_jwt(jobpilot_session)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user
