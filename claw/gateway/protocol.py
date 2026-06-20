"""Wire protocol helpers for the Claw gateway."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class WireRequest:
    """Inbound control-plane request frame."""
    id: str
    method: str
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    protocol_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = self.id


@dataclass
class WireResponse:
    id: str
    ok: bool
    result: Any = None
    error: Optional[str] = None


@dataclass
class WireEvent:
    event: str
    payload: Any = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


def make_response(request_id: str, *, ok: bool, result: Any = None, error: str | None = None) -> dict:
    return {"id": request_id, "ok": ok, "result": result, "error": error}


def make_event(event: str, payload: Any = None) -> dict:
    return {"type": "event", "event": event, "payload": payload, "id": str(uuid.uuid4())}
