# Copyright (c) 2026 Kenneth Stott
# Canary: 0b6e3f2a-7c91-4d58-a2e4-91f5c8d03b7e
#
# This source code is licensed under the Business Source License 1.1
# found in the LICENSE file in the root directory of this source tree.
#
# NOTICE: Use of this software for training artificial intelligence or
# machine learning models is strictly prohibited without explicit written
# permission from the copyright holder.

"""What a Polly turn uses and costs (REQ-2012).

Each model call reports its token usage: fresh input, output, and input read from or written to
the prompt cache. A turn's usage is the sum over its calls, tool round trips included, and is
reported at the end of the turn. Its cost is that usage times the model's price in
``polly.model_prices``, a table the operator sees and edits on the settings page (USD per million
tokens). A model with no price there has no cost to report.
"""

# Requirements: REQ-2012

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_MILLION = 1_000_000


class PriceTableError(ValueError):
    """An entry of ``polly.model_prices`` that cannot be read."""


@dataclass(frozen=True)
class Price:
    """USD per million tokens: fresh input, output, input read from the prompt cache, and input
    written to it."""

    input: float
    output: float
    cache_read: float
    cache_write: float


@dataclass(frozen=True)
class Usage:
    """The tokens one model call (or a turn's calls) used. ``input_tokens`` is the fresh input;
    input read from or written to the prompt cache is counted apart."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.calls + other.calls,
        )


def from_anthropic(usage: Any) -> Usage:
    """One Anthropic Messages call's usage. Its ``input_tokens`` already excludes cached input."""
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
        calls=1,
    )


def from_openai(usage: Any) -> Usage:
    """One OpenAI-shaped call's usage (aisuite's vendors, OpenRouter). Its ``prompt_tokens``
    includes the cached part, which ``prompt_tokens_details.cached_tokens`` names; OpenRouter
    reports what it wrote to the cache as ``cache_write_tokens`` there too."""
    details = getattr(usage, "prompt_tokens_details", None)
    cached = (getattr(details, "cached_tokens", None) or 0) if details is not None else 0
    written = (getattr(details, "cache_write_tokens", None) or 0) if details is not None else 0
    return Usage(
        input_tokens=usage.prompt_tokens - cached - written,
        output_tokens=usage.completion_tokens,
        cache_read_tokens=cached,
        cache_write_tokens=written,
        calls=1,
    )


def parse_prices(entries: list[str] | tuple[str, ...]) -> dict[str, Price]:
    """``polly.model_prices`` as a table: each entry is ``<model> <input> <output> <cache read>
    <cache write>``, USD per million tokens. An entry that does not read is refused, naming it."""
    table: dict[str, Price] = {}
    for entry in entries:
        parts = entry.split()
        if len(parts) != 5:
            raise PriceTableError(
                f"polly.model_prices entry {entry!r} is not '<model> <input> <output> "
                "<cache read> <cache write>' (USD per million tokens)"
            )
        try:
            numbers = [float(p) for p in parts[1:]]
        except ValueError as exc:
            raise PriceTableError(f"polly.model_prices entry {entry!r}: {exc}") from exc
        table[parts[0]] = Price(*numbers)
    return table


def prices() -> dict[str, Price]:
    """The operator's price table."""
    from provisa.core import settings_registry

    return parse_prices(settings_registry.value("polly.model_prices"))


def cost_usd(usage: Usage, price: Price) -> float:
    """What ``usage`` costs at ``price``."""
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / _MILLION


def usage_event(model: str, usage: Usage, provider_cost_usd: float | None = None) -> dict:
    """The turn's ``usage`` event: its tokens, and its cost at the model's price when the price
    table has one (``cost_usd`` is None when it has not). ``provider_cost_usd`` is what the
    provider itself billed, when it says (OpenRouter does)."""
    price = prices().get(model)
    return {
        "type": "usage",
        "model": model,
        "calls": usage.calls,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "cost_usd": None if price is None else round(cost_usd(usage, price), 8),
        "provider_cost_usd": provider_cost_usd,
    }
