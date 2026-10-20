"""Model providers behind one interface. Every call returns token usage and, where the
price is known, its cost, so Keel's Quartermaster can account for it."""

from wheelhouse.providers.base import Completion, Provider, ProviderError, Usage
from wheelhouse.providers.clients import (
    AnthropicProvider,
    OllamaProvider,
    OpenRouterProvider,
    choose_provider,
    live_check,
)
from wheelhouse.providers.pricing import PRICES, cost_usd

__all__ = [
    "PRICES",
    "AnthropicProvider",
    "Completion",
    "OllamaProvider",
    "OpenRouterProvider",
    "Provider",
    "ProviderError",
    "Usage",
    "choose_provider",
    "cost_usd",
    "live_check",
]
