"""AuthManager — JWT + API key verification for the Claw gateway."""
from __future__ import annotations

import logging
import os
from typing import Optional

from nodus_auth.jwt import InvalidTokenError, KeyRing, create_access_token, decode_access_token
from nodus_auth.schemas import AuthPrincipal

from claw.config.schema import GatewayConfig
from .store import ApiKeyStore

logger = logging.getLogger(__name__)

_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


class AuthManager:
    """Handles JWT token issuance and verification plus API key management.

    Auth is optional. If GatewayConfig.token is None and no SECRET_KEY is
    set, the gateway operates in open (no-auth) mode.
    """

    def __init__(self, config: GatewayConfig, state_dir: str = "~/.claw") -> None:
        self._config = config
        self._key_ring: Optional[KeyRing] = None
        self._enabled = False
        self._secret: Optional[str] = None

        # API key store: SQLite if state_dir given, in-memory for tests
        from pathlib import Path
        db_path = Path(state_dir).expanduser() / "auth.db"
        try:
            from claw.auth.sqlite_store import SqliteApiKeyStore
            self._api_key_store: ApiKeyStore = SqliteApiKeyStore(db_path)  # type: ignore[assignment]
            logger.debug("[auth] API key store: %s", db_path)
        except Exception as exc:
            logger.warning("[auth] SQLite key store unavailable (%s), using in-memory", exc)
            self._api_key_store = ApiKeyStore()

        secret = (
            config.token
            or os.environ.get("CLAW_SECRET_KEY")
            or os.environ.get("CLAW_GATEWAY_TOKEN")
        )
        if secret:
            self._key_ring = KeyRing(active=secret)
            self._secret = secret
            self._enabled = True
            logger.info("[auth] JWT auth enabled")
        else:
            logger.info("[auth] running in open mode (no auth)")

    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def api_key_store(self):  # ApiKeyStore | SqliteApiKeyStore
        return self._api_key_store

    # ------------------------------------------------------------------ #
    # JWT
    # ------------------------------------------------------------------ #

    def issue_token(self, user_id: str, scopes: list[str] | None = None) -> str:
        """Issue a JWT for *user_id*."""
        if not self._enabled or self._key_ring is None:
            raise RuntimeError("Auth not enabled — set CLAW_SECRET_KEY or gateway.token")
        from datetime import timedelta
        data = {"sub": user_id, "scopes": scopes or ["*"]}
        return create_access_token(
            data,
            key_ring=self._key_ring,
            expires_delta=timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES),
        )

    def verify_token(self, token: str) -> Optional[AuthPrincipal]:
        """Verify a JWT and return an AuthPrincipal, or None if invalid."""
        if not self._enabled or self._key_ring is None:
            return None
        try:
            payload = decode_access_token(token, key_ring=self._key_ring)
            user_id = payload.get("sub", "")
            scopes = payload.get("scopes", ["*"])
            return AuthPrincipal(user_id=user_id, auth_type="jwt", scopes=scopes)
        except InvalidTokenError:
            return None

    # ------------------------------------------------------------------ #
    # API key
    # ------------------------------------------------------------------ #

    def verify_api_key(self, raw_key: str) -> Optional[AuthPrincipal]:
        """Verify a raw API key and return an AuthPrincipal, or None."""
        record = self._api_key_store.verify(raw_key)
        if record is None:
            return None
        return AuthPrincipal(
            user_id=f"apikey:{record.key_id}",
            auth_type="api_key",
            scopes=record.scopes,
            key_id=record.key_id,
        )

    # ------------------------------------------------------------------ #
    # Unified verification (Bearer JWT or API key)
    # ------------------------------------------------------------------ #

    def verify(self, token_or_key: str) -> Optional[AuthPrincipal]:
        """Try JWT first, then API key. Returns None if auth is disabled."""
        if not self._enabled:
            return AuthPrincipal(user_id="anonymous", auth_type="open", scopes=["*"])

        # Try JWT
        principal = self.verify_token(token_or_key)
        if principal:
            return principal

        # Try API key
        return self.verify_api_key(token_or_key)

    def require(self, token_or_key: Optional[str]) -> AuthPrincipal:
        """Raise ValueError if the token/key is missing or invalid."""
        if not self._enabled:
            return AuthPrincipal(user_id="anonymous", auth_type="open", scopes=["*"])
        if not token_or_key:
            raise ValueError("Missing authentication token or API key")
        principal = self.verify(token_or_key)
        if principal is None:
            raise ValueError("Invalid or expired token")
        return principal
