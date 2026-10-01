"""Contract C3 - SessionContext (M1 -> M2, M3).

PRD4 section 4.3. Produced by M1's ``current_session()`` / ``require_role()``
dependencies (``app.shared.deps``) and consumed by every authenticated
endpoint in M2 and M3.

M1 and M3 each shipped a copy of this class. This is their union: M3's
defaults for ``account_status`` and ``issued_at`` (its tests build sessions
without them) plus M1's ``from_attributes`` config. M1 always passes every
field, so neither side's behaviour changes. See changes.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionContext(BaseModel):
    """Validated session identity passed from FastAPI dependency."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    email: str
    role: Literal["User", "Admin"]
    account_status: Literal["active", "disabled", "removed"] = "active"
    session_token: str
    issued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
