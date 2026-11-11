"""OIDC bearer-token validation (Keycloak) and role-based access control.

Tokens are RS256 JWTs. Keys come from the realm JWKS endpoint (internal URL); the issuer
is checked against the public realm URL; the authorized party must be the UI client.
Roles: realm roles operator, process_engineer, maintenance, admin.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request, WebSocket

from svc_common import config

ROLES = ("operator", "process_engineer", "maintenance", "admin")


@dataclass
class User:
    sub: str
    username: str
    roles: list[str]


class Verifier:
    def __init__(self) -> None:
        self.jwks_url = config.env("RGPF_OIDC_JWKS", "http://keycloak:8080/realms/rgpf/protocol/openid-connect/certs")
        self.issuer = config.env("RGPF_OIDC_ISSUER", "http://localhost:8080/realms/rgpf")
        self.clients = set(config.env("RGPF_OIDC_CLIENTS", "rgpf-ui").split(","))  # allowed azp values
        self.keys: dict[str, Any] = {}
        self._fetched = 0.0

    def _refresh(self) -> None:
        if time.time() - self._fetched < 60:
            return
        jwks = httpx.get(self.jwks_url, timeout=5).json()
        self.keys = {k["kid"]: jwt.PyJWK(k).key for k in jwks["keys"] if k.get("use", "sig") == "sig"}
        self._fetched = time.time()

    def verify(self, token: str) -> User:
        try:
            kid = jwt.get_unverified_header(token).get("kid", "")
            if kid not in self.keys:
                self._refresh()
            claims = jwt.decode(
                token,
                self.keys[kid],
                algorithms=["RS256"],
                issuer=self.issuer,
                options={"verify_aud": False, "require": ["exp", "iat", "iss", "sub"]},
            )
        except (jwt.PyJWTError, KeyError, httpx.HTTPError) as e:
            raise HTTPException(401, f"invalid token: {type(e).__name__}") from e
        if claims.get("azp") not in self.clients:
            raise HTTPException(401, "token not issued to an allowed client")
        roles = [r for r in claims.get("realm_access", {}).get("roles", []) if r in ROLES]
        return User(claims["sub"], claims.get("preferred_username", ""), roles)


VERIFIER = Verifier()


def current_user(request: Request) -> User:
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    user = VERIFIER.verify(h[7:])
    request.state.user = user
    return user


def ws_user(ws: WebSocket) -> User:
    token = ws.query_params.get("token", "")
    return VERIFIER.verify(token)


def require(*roles: str) -> Any:
    def dep(user: User = Depends(current_user)) -> User:
        if "admin" in user.roles or any(r in user.roles for r in roles):
            return user
        raise HTTPException(403, f"requires one of roles {roles}")

    return Depends(dep)
