"""Deep dive model tiering (ADR-0052 §4, amends ADR-0037).

ADR-0037 keeps one canonical provider + one model. The Deep dive needs three
tiers — cheap (volume), strong (the moat: reachability + exploit planning), and
judge (the adversarial challenge, which must out-rank the generator per
ADR-0050's anti-self-preference rule). We *derive* the tier map from the
configured provider's own lineup, so there's still one credential.

Thin-lineup providers (ollama / custom) fall back to the single configured model
for every tier — the judge is then not independent (the caller logs that).
"""

from __future__ import annotations

#: (cheap, strong, judge) model ids per provider, without the provider prefix.
_LINEUP: dict[str, tuple[str, str, str]] = {
    "anthropic": ("claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-8"),
    "openrouter": (
        "anthropic/claude-haiku-4.5",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-opus-4.8",
    ),
    "openai": ("gpt-5-mini", "gpt-5", "gpt-5"),
    "google": ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-pro"),
}

TIERS = ("cheap", "strong", "judge")


def resolve_tier_model_ids(model_full_id: str) -> dict[str, str]:
    """Derive ``{cheap, strong, judge}`` ``<provider>/<model>`` ids.

    Falls back to the single configured model for every tier when the provider
    has no known lineup (ollama / custom) or the id isn't ``provider/model``.
    """
    provider, sep, _ = model_full_id.partition("/")
    lineup = _LINEUP.get(provider)
    if not sep or lineup is None:
        return {tier: model_full_id for tier in TIERS}
    cheap, strong, judge = lineup
    return {
        "cheap": f"{provider}/{cheap}",
        "strong": f"{provider}/{strong}",
        "judge": f"{provider}/{judge}",
    }


def judge_is_independent(model_full_id: str) -> bool:
    """True when the judge tier out-ranks the strong tier (a real second opinion)."""
    ids = resolve_tier_model_ids(model_full_id)
    return ids["judge"] != ids["strong"]


def clearing_is_trusted(model_full_id: str) -> bool:
    """True when the config has a known strong-judge lineup, so the Deep dive may
    emit a DISMISSAL verdict (``unexploitable`` / ``false_positive``).

    Clearing is the only verdict that can HIDE a real vuln, so it requires a
    capable judge tier. A thin-lineup config (ollama / custom / unrecognized id)
    collapses every tier to one possibly-weak model — there the deep dive may
    DETECT (``real``) and FLAG (``needs_review``) on any tier, but must never
    auto-dismiss (the flash-judge false-clears were exactly this weak-judge
    failure). Known-lineup providers always derive a strong judge (opus / gpt-5 /
    pro), so dismissal is trusted."""
    provider, sep, model = model_full_id.partition("/")
    # A malformed id (no '/', e.g. "openai") isn't a valid provider/model config —
    # never trust dismissal on it.
    return bool(sep and model) and provider in _LINEUP


__all__ = ["TIERS", "clearing_is_trusted", "judge_is_independent", "resolve_tier_model_ids"]
