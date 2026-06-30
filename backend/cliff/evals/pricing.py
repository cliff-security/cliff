"""Approximate per-model token pricing for eval budget enforcement (ADR-0050 §4).

USD per 1M tokens, ``(input, output)`` — provider list prices, approximate. Used
to turn token usage into a ``$`` estimate so the runner can enforce ``max_usd``.
The **token + duration caps are the reliable hard limits**; the ``$`` estimate is
best-effort (returns ``None`` for an unpriced model, and the runner then skips
the ``$`` check rather than guessing). Update as prices change / models are added.
"""

from __future__ import annotations

# Match is by substring against the model id (e.g. "openrouter/anthropic/
# claude-haiku-4.5" matches "claude-haiku-4.5").
_PRICE_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4.5": (1.0, 5.0),
    "claude-sonnet-4": (3.0, 15.0),
    # The Deep dive's judge tier is opus (model_tiers._LINEUP). Without an opus
    # entry, estimate_cost_usd returns None for any judge call, which makes the
    # eval runner's _TokenAccumulator.total_usd() return None and silently
    # disables its $ budget cap the moment a single challenge stage runs. Keep
    # the opus family priced so the cap can never go blind.
    "claude-opus-4": (5.0, 25.0),
    "claude-opus-4.8": (5.0, 25.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
}


def _match(model_id: str | None) -> str | None:
    """Longest matching key wins, so a model with its OWN key isn't mispriced
    against a shorter prefix. A sub-model NOT in the table still falls back to
    its nearest priced sibling (e.g. ``gpt-5-mini`` → ``gpt-5``) — an
    over-estimate, which is the safe direction for a best-effort budget guard.
    Add the sub-model's own key when an exact price matters."""
    m = (model_id or "").lower()
    candidates = [k for k in _PRICE_USD_PER_MTOK if k in m]
    return max(candidates, key=len) if candidates else None


def estimate_cost_usd(
    model_id: str | None, input_tokens: int, output_tokens: int
) -> float | None:
    """USD estimate for a single run, or ``None`` if the model isn't priced."""
    key = _match(model_id)
    if key is None:
        return None
    in_price, out_price = _PRICE_USD_PER_MTOK[key]
    return input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price


__all__ = ["estimate_cost_usd"]
