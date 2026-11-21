# test_context.py
# Lesson 8: tests for context.py (request options, usage numbers), the Trace totals built on it,
# and the agent loop's append-only rule. No API keys or network: python test_context.py

import copy, json, os
from types import SimpleNamespace as NS

import context
from context import request_kwargs, usage_numbers


def edit(type_="clear_tool_uses_20250919", **fields):
    return NS(type=type_, **fields)


def response(usage, applied_edits=None, content=(), stop_reason="end_turn", **extra):
    return NS(usage=usage, content=list(content), stop_reason=stop_reason,
              context_management=NS(applied_edits=applied_edits), **extra)


def test_request_kwargs_enable_caching_and_clearing():
    kw = request_kwargs()
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["betas"] == ["context-management-2025-06-27"]
    edits = kw["context_management"]["edits"]
    assert len(edits) == 1
    assert edits[0] == {
        "type": "clear_tool_uses_20250919",
        "trigger": {"type": "input_tokens", "value": 8_000},
        "keep": {"type": "tool_uses", "value": 3},
        "clear_at_least": {"type": "input_tokens", "value": 2_000},
    }


def test_thresholds_are_sane():
    # clearing must be able to free its minimum before the trigger is reached again
    assert context.CLEAR_AT_LEAST_TOKENS < context.CLEAR_TRIGGER_TOKENS
    assert context.KEEP_TOOL_USES >= 1


def test_request_kwargs_returns_fresh_dict():
    kw = request_kwargs()
    kw["cache_control"]["type"] = "changed"
    kw["betas"].append("x")
    kw["context_management"]["edits"][0]["trigger"]["value"] = 1
    kw["context_management"]["edits"].append({})
    assert request_kwargs() == {
        "cache_control": {"type": "ephemeral"},
        "betas": [context.CONTEXT_BETA],
        "context_management": {"edits": [{
            "type": "clear_tool_uses_20250919",
            "trigger": {"type": "input_tokens", "value": context.CLEAR_TRIGGER_TOKENS},
            "keep": {"type": "tool_uses", "value": context.KEEP_TOOL_USES},
            "clear_at_least": {"type": "input_tokens", "value": context.CLEAR_AT_LEAST_TOKENS},
        }]},
    }
    assert context.CACHE_CONTROL == {"type": "ephemeral"}


def test_usage_without_cache_fields():
    r = NS(usage=NS(input_tokens=120, output_tokens=30))   # no context_management attr at all
    n = usage_numbers(r)
    assert n == {"input_tokens": 120, "output_tokens": 30, "cache_read": 0, "cache_write": 0,
                 "context_tokens": 120, "cleared_tool_uses": 0, "cleared_tokens": 0,
                 "edit_types": []}


def test_usage_none_cache_fields_count_as_zero():
    u = NS(input_tokens=10, output_tokens=5,
           cache_read_input_tokens=None, cache_creation_input_tokens=None)
    n = usage_numbers(NS(usage=u, context_management=None))
    assert (n["cache_read"], n["cache_write"], n["context_tokens"]) == (0, 0, 10)
    assert n["edit_types"] == []


def test_usage_cache_hit():
    u = NS(input_tokens=50, output_tokens=7,
           cache_read_input_tokens=4000, cache_creation_input_tokens=300)
    n = usage_numbers(response(u))
    assert (n["input_tokens"], n["cache_read"], n["cache_write"]) == (50, 4000, 300)
    assert n["context_tokens"] == 4350


def test_applied_edits_are_summed():
    edits = [edit(cleared_tool_uses=2, cleared_input_tokens=4100),
             edit(cleared_tool_uses=1, cleared_input_tokens=900)]
    n = usage_numbers(response(NS(input_tokens=1, output_tokens=1), edits))
    assert n["cleared_tool_uses"] == 3
    assert n["cleared_tokens"] == 5000
    assert n["edit_types"] == ["clear_tool_uses_20250919", "clear_tool_uses_20250919"]


def test_empty_applied_edits():
    for applied in ([], None):
        n = usage_numbers(response(NS(input_tokens=1, output_tokens=1), applied))
        assert (n["cleared_tool_uses"], n["cleared_tokens"], n["edit_types"]) == (0, 0, [])


def test_unknown_edit_type_does_not_crash():
    edits = [edit("some_future_edit_type"),          # no cleared_* fields at all
             edit(cleared_tool_uses=1, cleared_input_tokens=2500)]
    n = usage_numbers(response(NS(input_tokens=1, output_tokens=1), edits))
    assert n["cleared_tool_uses"] == 1
    assert n["cleared_tokens"] == 2500
    assert n["edit_types"] == ["some_future_edit_type", "clear_tool_uses_20250919"]


def block(**fields):
    """A fake content block: SDK blocks have .type and .model_dump()."""
    b = NS(**fields)
    b.model_dump = lambda: dict(fields)
    return b


def test_trace_totals_cache_and_clears():
    from trace import Trace
    t = Trace("q")
    try:
        r1 = response(NS(input_tokens=600, output_tokens=40, cache_read_input_tokens=0,
                         cache_creation_input_tokens=3000),
                      content=[block(type="text", text="a")], stop_reason="tool_use")
        r2 = response(NS(input_tokens=80, output_tokens=60, cache_read_input_tokens=3000,
                         cache_creation_input_tokens=900),
                      [edit(cleared_tool_uses=2, cleared_input_tokens=4100)],
                      content=[block(type="text", text="b")])
        t.model_call(0, r1)
        t.model_call(1, r2)
        assert t.steps == 2
        assert (t.tokens_in, t.tokens_out) == (680, 100)
        assert (t.cache_read, t.cache_write) == (3000, 3900)
        assert t.cleared_tokens == 4100
        assert t.context_peak == 3980          # max(600+0+3000, 80+3000+900)
        t.finish("done")

        events = [json.loads(line) for line in t.path.read_text(encoding="utf-8").splitlines()]
        calls = [e for e in events if e["event"] == "model_call"]
        assert calls[1]["cache_read"] == 3000 and calls[1]["context_tokens"] == 3980
        edits = [e for e in events if e["event"] == "context_edit"]
        assert len(edits) == 1
        assert edits[0]["step"] == 1
        assert edits[0]["edit_types"] == ["clear_tool_uses_20250919"]
        assert edits[0]["cleared_tool_uses"] == 2 and edits[0]["cleared_tokens"] == 4100
        end = events[-1]
        assert end["event"] == "run_end"
        assert (end["cache_read"], end["cache_write"]) == (3000, 3900)
        assert (end["cleared_tokens"], end["context_peak"]) == (4100, 3980)
    finally:
        t.path.unlink(missing_ok=True)


def test_loop_is_append_only_and_sends_context_options():
    # dummy keys BEFORE importing agent: tools.py and the SDK client read them at import time
    os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
    os.environ.setdefault("TAVILY_API_KEY", "test-key")
    import agent

    usage = NS(input_tokens=10, output_tokens=5,
               cache_read_input_tokens=0, cache_creation_input_tokens=0)

    def tool_turn(i):
        content = [block(type="thinking", thinking=f"plan {i}", signature=f"sig{i}"),
                   block(type="tool_use", id=f"tu_{i}", name="fetch_page",
                         input={"url": f"https://example.com/{i}"})]
        return response(usage, content=content, stop_reason="tool_use")

    scripted = [tool_turn(0), tool_turn(1),
                response(usage, content=[block(type="text", text="answer")])]
    recorded = []      # deep copies: what each call actually sent at that moment
    live = []          # the real kwargs objects, to check identity afterwards

    class FakeMessages:
        def create(self, **kw):
            recorded.append(copy.deepcopy(kw))
            live.append(kw)
            return scripted[len(recorded) - 1]

    fake_client = NS(beta=NS(messages=FakeMessages()))
    real_client, real_fetch = agent.client, agent.REGISTRY["fetch_page"]
    agent.client = fake_client
    agent.REGISTRY["fetch_page"] = (real_fetch[0], lambda args: f"page text of {args.url}")
    trace = agent.Trace("q")
    try:
        answer = agent.run("q", use_memory=False, trace=trace)
        assert answer == "answer"
        assert len(recorded) == 3

        expected = request_kwargs()
        for kw in recorded:
            assert kw["model"] == "claude-sonnet-5-5"
            assert "thinking" not in kw
            for key in ("cache_control", "betas", "context_management"):
                assert kw[key] == expected[key], key

        # append-only: each call's messages start with the previous call's messages exactly
        for prev, cur in zip(recorded, recorded[1:]):
            n = len(prev["messages"])
            assert len(cur["messages"]) > n
            assert cur["messages"][:n] == prev["messages"]

        # the assistant turns hold the response's own block objects, same order, thinking first
        messages = live[-1]["messages"]
        for i, r in enumerate(scripted[:2]):
            m = messages[1 + 2 * i]
            assert m["role"] == "assistant"
            assert len(m["content"]) == len(r.content)
            assert all(a is b for a, b in zip(m["content"], r.content))
            assert m["content"][0].type == "thinking"
            assert messages[2 + 2 * i]["content"][0]["tool_use_id"] == f"tu_{i}"
    finally:
        agent.client = real_client
        agent.REGISTRY["fetch_page"] = real_fetch
        trace.path.unlink(missing_ok=True)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} passed")
