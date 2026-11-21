# context.py
# Lesson 8: context management. Measure the prompt, cache the prefix, let the API clear old tool results.
#
# Every agent step resends the whole, growing `messages` list. Three things keep that affordable:
#   1. measure it: usage_numbers() splits each call's prompt into uncached / cache-read / cache-write
#   2. cache it:   automatic prompt caching reuses the unchanged prefix (steps 1..N-1) at a discount
#   3. trim it on the SERVER: context editing clears old tool results before the model sees them
#
# The append-only rule: never edit, filter or drop earlier `messages` entries client-side.
# claude-sonnet-5-5 thinks by default, so assistant turns contain thinking blocks whose validity is
# bound to the exact conversation before them; rewriting history returns a 400 (accounts created
# on/after 2026-08-31) and, even where it doesn't, busts the prompt cache from the edited point on.
# Server-side context editing does not count as an edit: our list stays intact, the API trims its view.
# Stdlib only on purpose: tests import this without an API key or the SDK.

# Beta flag that turns on server-side context editing (`context_management` below).
CONTEXT_BETA = "context-management-2025-06-27"

# Top-level automatic caching: the API puts the cache breakpoint at the end of each request,
# so the next step reads everything before it from cache. 5-minute TTL, refreshed on every hit.
# The prefix must be >= 512 tokens on Sonnet 5.5 to be cached at all. Cache reads cost 0.05x input,
# writes 1.25x, so a 2-step run can pay for a write it never reads; caching pays from step 3 on.
CACHE_CONTROL = {"type": "ephemeral"}

# Clear old tool results once the prompt passes this many input tokens. A search plus three
# fetched pages is ~7.5-8k, so this is deliberately low so a learner sees clearing fire.
# The API default is 100_000 and production values belong near that; at this scale clearing
# is context hygiene (the model stops re-reading stale pages), not a cost saving.
CLEAR_TRIGGER_TOKENS = 8_000

# Keep the most recent N tool uses intact (the API default). 3 keeps a whole batch of up to
# three parallel fetches, so the model never loses a page it fetched in its latest step.
KEEP_TOOL_USES = 3

# Only clear when at least this many tokens are freed (~one fetched page). Clearing rewrites the
# cache from the cleared point onward, so a tiny clear would cost more in cache writes than it saves.
CLEAR_AT_LEAST_TOKENS = 2_000


def request_kwargs() -> dict:
    """Extra kwargs for client.beta.messages.create: caching + server-side tool-result clearing.
    Builds a fresh dict (nested dicts too) every call, so a caller mutating it can't leak into the next."""
    return {
        "cache_control": dict(CACHE_CONTROL),
        "betas": [CONTEXT_BETA],
        "context_management": {
            "edits": [{
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": CLEAR_TRIGGER_TOKENS},
                "keep": {"type": "tool_uses", "value": KEEP_TOOL_USES},
                "clear_at_least": {"type": "input_tokens", "value": CLEAR_AT_LEAST_TOKENS},
            }],
        },
    }


def usage_numbers(response) -> dict:
    """The context numbers of one model call, as plain ints (None / missing fields count as 0).
    With caching on, usage.input_tokens is only the UNCACHED part; the real prompt size is
    input_tokens + cache_read + cache_write."""
    u = getattr(response, "usage", None)
    input_tokens = getattr(u, "input_tokens", 0) or 0
    output_tokens = getattr(u, "output_tokens", 0) or 0
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0

    cm = getattr(response, "context_management", None)
    edits = getattr(cm, "applied_edits", None) or []
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "context_tokens": input_tokens + cache_read + cache_write,
        # edit types we don't know (e.g. clear_thinking) lack these fields and add 0
        "cleared_tool_uses": sum(getattr(e, "cleared_tool_uses", 0) or 0 for e in edits),
        "cleared_tokens": sum(getattr(e, "cleared_input_tokens", 0) or 0 for e in edits),
        "edit_types": [getattr(e, "type", "unknown") for e in edits],
    }
