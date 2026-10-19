"""HTTP clients for Anthropic, OpenRouter and Ollama.

Plain httpx calls rather than three SDKs, so every provider behaves the same way:
timeouts, error messages without secrets, and usage returned with every completion.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from wheelhouse.config import Settings
from wheelhouse.providers.base import Completion, ProviderError, Usage
from wheelhouse.providers.pricing import cost_usd

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _post(url: str, headers: dict[str, str], body: dict[str, Any], who: str) -> dict[str, Any]:
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
    except httpx.HTTPError as err:
        raise ProviderError(f"{who}: request failed ({type(err).__name__})") from None
    if resp.status_code >= 400:
        raise ProviderError(f"{who}: HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, dict):
        raise ProviderError(f"{who}: unexpected response")
    return data


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-haiku-5-5") -> None:
        self._key = api_key
        self.model = model

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model!r})"

    def complete(self, system: str, user: str, max_tokens: int = 512) -> Completion:
        start = time.monotonic()
        data = _post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": self._key, "anthropic-version": "2023-06-01"},
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            "anthropic",
        )
        text = "".join(b.get("text", "") for b in data.get("content", []) if isinstance(b, dict))
        u = data.get("usage", {})
        inp, out = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
        cost = cost_usd(self.model, inp, out)
        return Completion(
            text,
            Usage(
                self.name,
                str(data.get("model", self.model)),
                inp,
                out,
                cost,
                "computed" if cost is not None else "unknown",
            ),
            int((time.monotonic() - start) * 1000),
        )


class OpenRouterProvider:
    name = "openrouter"

    def __init__(self, api_key: str, model: str) -> None:
        self._key = api_key
        self.model = model

    def __repr__(self) -> str:
        return f"OpenRouterProvider(model={self.model!r})"

    def complete(self, system: str, user: str, max_tokens: int = 512) -> Completion:
        start = time.monotonic()
        data = _post(
            "https://openrouter.ai/api/v1/chat/completions",
            {"Authorization": f"Bearer {self._key}"},
            {
                "model": self.model,
                "max_tokens": max_tokens,
                "usage": {"include": True},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            "openrouter",
        )
        choices = data.get("choices") or [{}]
        text = str(choices[0].get("message", {}).get("content") or "")
        u = data.get("usage", {})
        reported = u.get("cost")
        return Completion(
            text,
            Usage(
                self.name,
                str(data.get("model", self.model)),
                int(u.get("prompt_tokens", 0)),
                int(u.get("completion_tokens", 0)),
                float(reported) if reported is not None else None,
                "reported" if reported is not None else "unknown",
            ),
            int((time.monotonic() - start) * 1000),
        )

    def key_status(self) -> dict[str, Any]:
        """Key validity and limits. Costs nothing."""
        try:
            resp = httpx.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as err:
            raise ProviderError(f"openrouter: request failed ({type(err).__name__})") from None
        if resp.status_code >= 400:
            raise ProviderError(f"openrouter: HTTP {resp.status_code}")
        data = resp.json().get("data", {})
        return data if isinstance(data, dict) else {}


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = 512) -> Completion:
        start = time.monotonic()
        data = _post(
            f"{self.base_url}/api/chat",
            {},
            {
                "model": self.model,
                "stream": False,
                "options": {"num_predict": max_tokens},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            "ollama",
        )
        text = str(data.get("message", {}).get("content", ""))
        return Completion(
            text,
            Usage(
                self.name,
                self.model,
                int(data.get("prompt_eval_count", 0)),
                int(data.get("eval_count", 0)),
                0.0,
                "computed",
            ),
            int((time.monotonic() - start) * 1000),
        )


def live_check(settings: Settings) -> list[str]:
    """One tiny call per configured provider. Prints usage and cost, never keys."""
    lines: list[str] = []
    if settings.anthropic_api_key:
        try:
            c = AnthropicProvider(settings.anthropic_api_key.get_secret_value()).complete(
                "Reply with one word.", "Say ok.", max_tokens=5
            )
            lines.append(
                f"  anthropic   live ok: {c.usage.model}, {c.usage.input_tokens}+"
                f"{c.usage.output_tokens} tokens, ${c.usage.cost_usd}, {c.latency_ms} ms"
            )
        except ProviderError as err:
            lines.append(f"  anthropic   live FAILED: {err}")
    if settings.openrouter_api_key:
        try:
            info = OpenRouterProvider(settings.openrouter_api_key.get_secret_value(), "")
            status = info.key_status()
            lines.append(
                f"  openrouter  key ok: usage ${status.get('usage')}, limit "
                f"{status.get('limit')}, remaining {status.get('limit_remaining')}"
            )
        except ProviderError as err:
            lines.append(f"  openrouter  key check FAILED: {err}")
    if settings.ollama_base_url:
        try:
            r = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=TIMEOUT)
            lines.append(f"  ollama      reachable: HTTP {r.status_code}")
        except httpx.HTTPError as err:
            lines.append(f"  ollama      unreachable ({type(err).__name__})")
    return lines
