"""ApiKeyStore — in-memory registry of named API keys (hashed)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from nodus_auth.keys import generate_key, hash_key

logger = logging.getLogger(__name__)


@dataclass
class ApiKeyRecord:
    key_id: str
    key_hash: str
    label: str
    scopes: list[str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: Optional[datetime] = None
    enabled: bool = True


class ApiKeyStore:
    """Thread-safe in-memory store for API keys.

    Keys are stored as SHA-256 hashes. The raw key is returned once
    at creation time and never stored.
    Phase 6 swaps this for aiosqlite persistence.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, ApiKeyRecord] = {}     # key_id → record
        self._by_hash: dict[str, str] = {}             # key_hash → key_id

    def create(self, label: str, scopes: list[str] | None = None) -> tuple[str, ApiKeyRecord]:
        """Generate a new API key. Returns (raw_key, record). Store the raw_key securely."""
        raw_key, key_hash = generate_key(prefix="claw_")
        key_id = raw_key.split("_")[1][:8] if "_" in raw_key else raw_key[:8]
        record = ApiKeyRecord(
            key_id=key_id,
            key_hash=key_hash,
            label=label,
            scopes=scopes or ["*"],
        )
        self._by_id[key_id] = record
        self._by_hash[key_hash] = key_id
        logger.info("[auth] created API key key_id=%s label=%r", key_id, label)
        return raw_key, record

    def verify(self, raw_key: str) -> Optional[ApiKeyRecord]:
        """Verify a raw key and return its record if valid, else None."""
        key_hash = hash_key(raw_key)
        key_id = self._by_hash.get(key_hash)
        if key_id is None:
            return None
        record = self._by_id.get(key_id)
        if record is None or not record.enabled:
            return None
        record.last_used = datetime.now(timezone.utc)
        return record

    def revoke(self, key_id: str) -> bool:
        record = self._by_id.get(key_id)
        if record is None:
            return False
        record.enabled = False
        logger.info("[auth] revoked API key key_id=%s", key_id)
        return True

    def list_keys(self) -> list[ApiKeyRecord]:
        return [r for r in self._by_id.values() if r.enabled]

    def get(self, key_id: str) -> Optional[ApiKeyRecord]:
        return self._by_id.get(key_id)
