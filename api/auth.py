import time
from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import PyJWKClientError

from api.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=True)


class _ThrottledJWKClient(PyJWKClient):
    """Refetches the key set for an unknown `kid` at most once a minute; PyJWT would
    otherwise make an outbound request for every forged token."""

    _MIN_REFRESH_SECONDS = 60.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_refresh = float("-inf")

    def get_signing_keys(self, refresh: bool = False) -> list[PyJWK]:
        if refresh:
            now = time.monotonic()
            refresh = now - self._last_refresh >= self._MIN_REFRESH_SECONDS
            if refresh:
                self._last_refresh = now
        return super().get_signing_keys(refresh=refresh)


_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: str
    email: str | None
    role: str | None
    claims: dict[str, Any]


def _get_jwks_client(settings: Settings) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = _ThrottledJWKClient(settings.jwks_url, cache_keys=True)
    return _jwks_client


def verify_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except (jwt.PyJWTError, PyJWKClientError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    alg = header.get("alg")
    require = {"require": ["exp", "sub", "iss", "aud"]}

    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="HS256 token received but SUPABASE_JWT_SECRET is not configured",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                issuer=settings.jwt_issuer,
                options=require,
            )

        signing_key = _get_jwks_client(settings).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=settings.jwt_issuer,
            options=require,
        )
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    claims = verify_access_token(credentials.credentials, settings)
    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(
        id=user_id,
        email=claims.get("email"),
        role=claims.get("role"),
        claims=claims,
    )
