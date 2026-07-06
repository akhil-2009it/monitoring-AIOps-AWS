"""Cognito JWT verification — analyst / responder / admin groups.

Same shape as ../mlops auth, but with role enforcement helpers tailored
to the SOC use case:
  - analyst   : read alerts
  - responder : analyst + label alerts (feedback)
  - admin     : everything + admin endpoints
"""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import HTTPException, Request, status

JWKS_TTL_SEC = 24 * 3600
ROLES = ("analyst", "responder", "admin")


def _is_auth_disabled() -> bool:
    return os.getenv("MLOPS_AUTH_DISABLED", "").lower() in ("1", "true", "yes")


class _JWKSCache:
    def __init__(self) -> None:
        self._keys: dict[str, dict] = {}
        self._fetched_at: float = 0.0

    def get(self, region: str, user_pool_id: str, kid: str) -> dict | None:
        if not self._keys or time.time() - self._fetched_at > JWKS_TTL_SEC:
            self._refresh(region, user_pool_id)
        return self._keys.get(kid)

    def _refresh(self, region: str, user_pool_id: str) -> None:
        import json as _json
        import urllib.request

        url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = _json.loads(resp.read())
        self._keys = {k["kid"]: k for k in data["keys"]}
        self._fetched_at = time.time()


_JWKS = _JWKSCache()


def verify_token(token: str) -> dict[str, Any]:
    if _is_auth_disabled():
        return {"sub": "local-dev", "cognito:groups": ["admin"]}

    region = os.environ["MLOPS_COGNITO_REGION"]
    user_pool_id = os.environ["MLOPS_COGNITO_USER_POOL_ID"]
    client_id = os.environ.get("MLOPS_COGNITO_CLIENT_ID")

    try:
        from jose import jwt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("python-jose required") from exc

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise jwt.JWTError("missing kid")
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token header: {exc}")

    key = _JWKS.get(region, user_pool_id, kid)
    if key is None:
        _JWKS._refresh(region, user_pool_id)
        key = _JWKS.get(region, user_pool_id, kid)
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown signing key")

    try:
        return jwt.decode(
            token, key, algorithms=["RS256"],
            audience=client_id,
            issuer=f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}",
            options={"verify_aud": client_id is not None},
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}")


async def auth_dependency(request: Request) -> dict[str, Any]:
    if _is_auth_disabled():
        return {"sub": "local-dev", "cognito:groups": ["admin"]}
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing Bearer token")
    return verify_token(auth[7:].strip())


def require_role(claims: dict, required: str) -> None:
    """Raise 403 unless `claims` has a group that satisfies `required`."""
    groups = claims.get("cognito:groups", []) or []
    # admin > responder > analyst
    rank = {"analyst": 1, "responder": 2, "admin": 3}
    have = max((rank.get(g, 0) for g in groups), default=0)
    need = rank.get(required, 0)
    if have < need:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role {required}")
