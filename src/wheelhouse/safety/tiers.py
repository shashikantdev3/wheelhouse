"""Action tiers. See docs/safety-model.md."""

from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    LOOK = "look"
    """Read-only and allowlisted. Runs without approval."""

    TOUCH = "touch"
    """Changes state but is reversible. Runs only after a human approves this exact step."""

    NEVER = "never"
    """Destructive or irreversible. Refused in code; no approval can unlock it."""


class Verdict(StrEnum):
    RUN = "run"
    NEEDS_APPROVAL = "needs_approval"
    REFUSED = "refused"
