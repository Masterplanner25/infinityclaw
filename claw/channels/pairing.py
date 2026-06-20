"""PairingStore — SQLite-backed device/peer pairing code management."""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CODE_TTL = 300  # pairing codes expire in 5 minutes


@dataclass
class PairingRecord:
    code: str
    channel_id: str
    peer_id: str
    created_at: float
    approved: bool = False

    def is_expired(self) -> bool:
        return not self.approved and (time.time() - self.created_at) > _CODE_TTL


class PairingStore:
    """Manages pairing codes for gated channel access.

    Phase 4 uses in-memory storage; Phase 5 swaps to aiosqlite.
    """

    def __init__(self) -> None:
        self._records: dict[str, PairingRecord] = {}  # code → record
        self._approved: dict[str, set[str]] = {}       # channel_id → {peer_id}

    def generate_code(self, channel_id: str, peer_id: str) -> str:
        """Generate a 6-char alphanumeric pairing code."""
        code = secrets.token_hex(3).upper()  # e.g. "A3F9C1"
        self._records[code] = PairingRecord(
            code=code,
            channel_id=channel_id,
            peer_id=peer_id,
            created_at=time.time(),
        )
        logger.info("[pairing] code=%s channel=%s peer=%s (TTL=%ds)", code, channel_id, peer_id, _CODE_TTL)
        return code

    def approve(self, code: str) -> Optional[PairingRecord]:
        """Approve a pairing code. Codes are single-use — returns None if already used."""
        record = self._records.get(code)
        if record is None:
            logger.warning("[pairing] unknown code=%s", code)
            return None
        if record.approved:
            logger.warning("[pairing] already-used code=%s", code)
            return None
        if record.is_expired():
            logger.warning("[pairing] expired code=%s", code)
            del self._records[code]
            return None
        record.approved = True
        self._approved.setdefault(record.channel_id, set()).add(record.peer_id)
        logger.info("[pairing] approved channel=%s peer=%s", record.channel_id, record.peer_id)
        return record

    def is_paired(self, channel_id: str, peer_id: str) -> bool:
        return peer_id in self._approved.get(channel_id, set())

    def paired_peers(self, channel_id: str) -> set[str]:
        return set(self._approved.get(channel_id, set()))

    def revoke(self, channel_id: str, peer_id: str) -> bool:
        peers = self._approved.get(channel_id, set())
        if peer_id in peers:
            peers.discard(peer_id)
            logger.info("[pairing] revoked channel=%s peer=%s", channel_id, peer_id)
            return True
        return False
