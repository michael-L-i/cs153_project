"""Supabase JWT verification for FastAPI.

Supabase's new key system signs tokens with ES256 (asymmetric) and exposes
the public key set at /auth/v1/.well-known/jwks.json. Older projects sign
with HS256 using a shared secret. We support both: JWKS first, then fall
back to the shared secret if SUPABASE_JWT_SECRET is set.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request, status

from newsletter.config import get_settings


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient | None:
    settings = get_settings()
    if not settings.supabase_url:
        return None
    url = settings.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def _decode(token: str) -> dict:
    settings = get_settings()

    client = _jwks_client()
    if client is not None:
        try:
            signing_key = client.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")
        except (jwt.PyJWKClientError, jwt.InvalidTokenError):
            pass  # may be a legacy HS256 token — try the secret below

    if settings.supabase_jwt_secret:
        try:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")
        except jwt.InvalidTokenError:
            pass

    if client is None and not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth is not configured on this server.",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")


def get_current_user(request: Request) -> AuthUser:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = header.split(" ", 1)[1].strip()
    claims = _decode(token)
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing subject.")
    return AuthUser(id=sub, email=claims.get("email"))


CurrentUser = Depends(get_current_user)
