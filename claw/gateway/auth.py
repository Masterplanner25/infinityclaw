"""Gateway auth — JWT, API key, and legacy bearer token validation."""
from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import HTTPException, WebSocket, status
from nodus_auth.schemas import AuthPrincipal

logger = logging.getLogger(__name__)


class GatewayAuth:
    """Validates auth for WS upgrades and HTTP endpoints.

    Accepts:
    1. JWT Bearer token (via AuthManager)
    2. API key (via AuthManager)
    3. Legacy static bearer token (backward compat with gateway.token)

    Auth is disabled when neither AuthManager is enabled nor a static
    token is configured — all connections are accepted.
    """

    def __init__(
        self,
        static_token: Optional[str] = None,
        auth_manager=None,  # AuthManager | None
    ) -> None:
        self._static_token = static_token.strip() if static_token else None
        self._auth_manager = auth_manager

    @property
    def enabled(self) -> bool:
        if self._auth_manager and self._auth_manager.is_enabled():
            return True
        return bool(self._static_token)

    def verify_principal(self, presented: str | None) -> Optional[AuthPrincipal]:
        """Try all auth methods. Returns None if no credential matches."""
        if not self.enabled:
            return AuthPrincipal(user_id="anonymous", auth_type="open", scopes=["*"])

        if not presented:
            return None

        # AuthManager handles JWT + API key
        if self._auth_manager and self._auth_manager.is_enabled():
            principal = self._auth_manager.verify(presented)
            if principal:
                return principal

        # Legacy static bearer token
        if self._static_token and hmac.compare_digest(presented.strip(), self._static_token):
            return AuthPrincipal(user_id="admin", auth_type="static", scopes=["*"])

        return None

    async def verify_ws(self, websocket: WebSocket, token: Optional[str] = None) -> Optional[AuthPrincipal]:
        """Check auth on a WS upgrade. Closes with 403 if invalid."""
        if not self.enabled:
            return AuthPrincipal(user_id="anonymous", auth_type="open", scopes=["*"])

        presented = (
            token
            or websocket.query_params.get("token")
            or _strip_bearer(websocket.headers.get("authorization"))
            or websocket.headers.get("x-api-key")
            or websocket.headers.get("x-claw-token")
        )

        principal = self.verify_principal(presented)
        if principal is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise HTTPException(status_code=403, detail="Invalid or missing token")
        return principal

    async def verify_http(self, request_headers: dict) -> Optional[AuthPrincipal]:
        """Extract and verify auth from HTTP request headers."""
        if not self.enabled:
            return AuthPrincipal(user_id="anonymous", auth_type="open", scopes=["*"])
        presented = (
            _strip_bearer(request_headers.get("authorization"))
            or request_headers.get("x-api-key")
        )
        return self.verify_principal(presented)


def _strip_bearer(value: str | None) -> str | None:
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value.strip()
