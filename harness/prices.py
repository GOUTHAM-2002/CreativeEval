"""Model registry (key -> route + slug) and a $/M-token table used only for cross-check estimates."""

MODELS = {
    "fable5.1": {"route": "cc", "slug": "anthropic/claude-fable-5.1", "api_id": "claude-fable-5-1"},
    "fable5": {"route": "cc", "slug": "anthropic/claude-fable-5", "api_id": "claude-fable-5"},
    "opus5": {"route": "cc", "slug": "anthropic/claude-opus-5", "api_id": "claude-opus-5"},
    "sonnet5": {"route": "cc", "slug": "anthropic/claude-sonnet-5", "api_id": "claude-sonnet-5"},
    "haiku4.5": {"route": "cc", "slug": "anthropic/claude-haiku-4.5", "api_id": "claude-haiku-4-5"},
    "astra": {"route": "or", "slug": "openai/gpt-6-astra"},
    "sol": {"route": "or", "slug": "openai/gpt-5.6-sol"},
    "fake": {"route": "fake", "slug": "fake/scripted"},
}

# UNVERIFIED placeholders, $ per 1M tokens: (input, cache_read, cache_write, output). Anthropic rows follow the
# list prices in the bundled claude-api reference (cached 2026-06-24); OpenRouter may bill differently and the
# OpenAI rows are guesses. Reported cost (claude `result.total_cost_usd`, OpenRouter `usage.cost`) always wins;
# this table only feeds `cost_estimate_usd` and the ledger's "larger of the two" rule.
PRICES = {
    "anthropic/claude-fable-5.1": (10.0, 1.0, 12.5, 50.0),
    "anthropic/claude-fable-5": (10.0, 1.0, 12.5, 50.0),
    "anthropic/claude-opus-5": (5.0, 0.5, 6.25, 25.0),
    "anthropic/claude-sonnet-5": (2.0, 0.2, 2.5, 10.0),
    "anthropic/claude-haiku-4.5": (1.0, 0.1, 1.25, 5.0),
    "openai/gpt-6-astra": (10.0, 2.5, 10.0, 50.0),
    "openai/gpt-5.6-sol": (5.0, 1.25, 5.0, 25.0),
    "fake/scripted": (0.0, 0.0, 0.0, 0.0),
}
FALLBACK_PRICE = (10.0, 1.0, 12.5, 50.0)


def resolve(model_key: str) -> dict:
    if model_key not in MODELS:
        raise KeyError(f"unknown model key {model_key!r}; known: {', '.join(MODELS)}")
    return {"key": model_key, **MODELS[model_key]}


def price_of(slug: str):
    base = slug.split(":")[0]
    for k, v in PRICES.items():
        if base == k or base.endswith("/" + k.split("/")[-1]) or base.replace("-", "").replace(".", "") == k.split("/")[-1].replace("-", "").replace(".", ""):
            return v
    return FALLBACK_PRICE


def estimate_usd(slug: str, input_tokens=0, cache_read=0, cache_write=0, output_tokens=0) -> float:
    pin, pcr, pcw, pout = price_of(slug)
    return round((input_tokens * pin + cache_read * pcr + cache_write * pcw + output_tokens * pout) / 1e6, 6)
