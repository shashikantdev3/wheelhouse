"""Prices in US dollars per million tokens, as published by the provider.

Checked 2026-10-19 on platform.claude.com/docs/en/about-claude/pricing. Prices change;
a model missing here gets cost_source "unknown" rather than a guess.
"""

from __future__ import annotations

# model: (input, output, input above long-prompt threshold, output above it, threshold)
PRICES: dict[str, tuple[float, float, float, float, int]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.50, 2.50, 100_000),
    "claude-sonnet-5-5": (2.0, 10.0, 2.0, 10.0, 0),
    "claude-opus-5-5": (4.0, 20.0, 4.0, 20.0, 0),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = PRICES.get(model)
    if price is None:
        return None
    inp, out, inp_long, out_long, threshold = price
    if threshold and input_tokens > threshold:
        inp, out = inp_long, out_long
    return round((input_tokens * inp + output_tokens * out) / 1_000_000, 8)
