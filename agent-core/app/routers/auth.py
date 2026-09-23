"""Auth — email+password, Google OAuth, and an optional GitHub connect.

Login is provider-agnostic: email+password or "Sign in with Google" both
work for any job seeker, not just developers. GitHub is no longer required
to use JobPilot at all — it's a separate, optional connection made later
(profile screen, `/auth/github/connect`) purely to grant Phase 3's RAG
ingestion read access to the user's repos. See docs/DESIGN_DECISIONS.md,
"Auth model."

Whichever path succeeds mints our own short-lived JWT and sets it as an
httpOnly cookie — session mechanics are unchanged from Phase 1. We never
hand a third-party token (Google's or GitHub's) to the frontend.
"""

import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jobpilot_shared.auth import (
    build_github_authorize_url,
    build_google_authorize_url,
    create_session_jwt,
    exchange_code_for_github_token,
    exchange_code_for_google_token,
    fetch_github_user,
    fetch_google_user,
    hash_password,
    verify_password,
)
from jobpilot_shared.config import settings
from jobpilot_shared.db import get_session
from jobpilot_shared.models import User

from app.deps import SESSION_COOKIE_NAME, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

# Reused for both the Google and GitHub handshakes — only one OAuth flow is
# ever in flight for a given browser at a time, so one cookie name is fine.
OAUTH_STATE_COOKIE = "jobpilot_oauth_state"


def _set_session_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_jwt(user_id),
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
    )


# --- Email + password -----------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
async def register(
    req: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    existing = await session.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 8 characters"
        )

    user = User(email=req.email, password_hash=hash_password(req.password), name=req.name)
    session.add(user)
    await session.commit()
    await session.refresh(user)

    _set_session_cookie(response, str(user.id))
    return {"id": str(user.id), "email": user.email}


@router.post("/login")
async def login(
    req: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    # Same generic error whether the email doesn't exist, has no password
    # (Google-only account), or the password is wrong — a login form
    # shouldn't reveal which of those it was.
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if user is None or user.password_hash is None or not verify_password(req.password, user.password_hash):
        raise invalid

    _set_session_cookie(response, str(user.id))
    return {"id": str(user.id), "email": user.email}


# --- Google OAuth (primary login) -----------------------------------------


@router.get("/google/login")
async def google_login() -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    redirect = RedirectResponse(build_google_authorize_url(state))
    redirect.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, max_age=600, samesite="lax")
    return redirect


@router.get("/google/callback")
async def google_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
    jobpilot_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    if not jobpilot_oauth_state or state != jobpilot_oauth_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch — possible CSRF, restart login")

    google_token = await exchange_code_for_google_token(code)
    profile = await fetch_google_user(google_token)

    google_id = str(profile["sub"])
    result = await session.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user is None:
        # Link to an existing email+password account with the same email
        # instead of creating a duplicate user.
        existing = await session.execute(select(User).where(User.email == profile.get("email")))
        user = existing.scalar_one_or_none()

        if user is None:
            user = User(
                email=profile["email"],
                google_id=google_id,
                name=profile.get("name"),
                avatar_url=profile.get("picture"),
            )
            session.add(user)
        else:
            user.google_id = google_id

    await session.commit()
    await session.refresh(user)

    redirect = RedirectResponse(settings.frontend_url)
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    _set_session_cookie(redirect, str(user.id))
    return redirect


# --- GitHub connect (optional — Phase 3 RAG only, never required) --------


@router.get("/github/connect")
async def github_connect(user: User = Depends(get_current_user)) -> RedirectResponse:
    state = secrets.token_urlsafe(24)
    redirect = RedirectResponse(build_github_authorize_url(state))
    redirect.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, max_age=600, samesite="lax")
    return redirect


@router.get("/github/callback")
async def github_callback(
    code: str,
    state: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    jobpilot_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    if not jobpilot_oauth_state or state != jobpilot_oauth_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch — possible CSRF, restart login")

    github_token = await exchange_code_for_github_token(code)
    profile = await fetch_github_user(github_token)

    user.github_id = str(profile["id"])
    user.github_username = profile.get("login", user.github_username)
    await session.commit()

    redirect = RedirectResponse(f"{settings.frontend_url}/profile")
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    return redirect


# --- Session -----------------------------------------------------------


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "google_linked": user.google_id is not None,
        "github_linked": user.github_id is not None,
        "github_username": user.github_username,
    }


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "logged out"}
