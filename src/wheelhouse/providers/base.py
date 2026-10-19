from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(RuntimeError):
    """A provider call failed. The message never contains the API key."""


@dataclass(frozen=True)
class Usage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    cost_source: str  # reported, computed, unknown


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage
    latency_ms: int


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int = 512) -> Completion: ...
