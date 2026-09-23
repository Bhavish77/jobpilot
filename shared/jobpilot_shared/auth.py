"""Password hashing, Google OAuth exchange, GitHub OAuth exchange (connect
flow only), and our own session JWT.

Design-doc decision (updated — see "Auth model"): login is email+password or
Google, so JobPilot works for any job seeker, not just developers with a
GitHub account. GitHub OAuth is kept here purely for the optional
`/auth/github/connect` flow, used later from the profile screen to grant
Phase 3's RAG ingestion read access to the user's repos.

We never hand a third-party access token (Google's or GitHub's) to the
frontend; we mint our own short-lived JWT instead and keep third-party
tokens server-side only.
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import bcrypt
import httpx
import jwt

from jobpilot_shared.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPES = "openid email profile"


def build_google_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_google_token(code: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise ValueError(f"Google token exchange failed: {data}")
        return data["access_token"]


async def fetch_google_user(google_access_token: str) -> dict[str, Any]:
    """Returns Google's userinfo payload — `sub` is the stable Google user
    id, `email`/`name`/`picture` are what we copy onto our own User row."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

# Just `repo` — GitHub is no longer a login path, so we don't need
# read:user/user:email here; email/name/avatar already come from
# email+password registration or Google.
GITHUB_SCOPES = "repo"


def build_github_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_redirect_uri,
        "scope": GITHUB_SCOPES,
        "state": state,
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_github_token(code: str) -> str:
    """The server-side half of the OAuth flow: trade a short-lived code
    (plus our client secret, which the browser never sees) for an access
    token. This call happens from agent-core, never from the frontend."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": settings.github_redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" not in data:
            raise ValueError(f"GitHub token exchange failed: {data}")
        return data["access_token"]


async def fetch_github_user(github_access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {github_access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def create_session_jwt(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_session_jwt(token: str) -> str:
    """Returns the user_id (sub claim). Raises jwt.PyJWTError on anything
    invalid or expired — callers turn that into a 401, they don't catch it
    silently."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return payload["sub"]
