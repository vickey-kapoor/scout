# test_evals.py
# Tests for the grader in evals.py. An eval that wrongly PASSES is worse than no eval,
# because you trust it. No API keys or network needed:
#
#   python test_evals.py

from types import SimpleNamespace

from evals import grade

CASE = {"id": "t", "question": "q", "expect": ["5432"], "domains": ["postgresql.org"],
        "max_steps": 3}
GOOD = "The default port is 5432 (https://www.postgresql.org/docs/current/runtime-config.html)."


def run(stop_reason="end_turn", steps=2):
    """Stand-in for a Trace: grade() only reads these two fields."""
    return SimpleNamespace(stop_reason=stop_reason, steps=steps)


def failed(checks: dict) -> set:
    return {k for k, ok in checks.items() if not ok}


def test_good_answer_passes():
    assert failed(grade(CASE, GOOD, run())) == set()


def test_cut_off_answer_is_not_finished():
    # contains the fact and a URL, but the model hit max_tokens mid-answer
    assert failed(grade(CASE, GOOD, run(stop_reason="max_tokens"))) == {"finished"}


def test_max_steps_stop_is_not_finished():
    # agent.run() returns this when MAX_STEPS runs out; the last call asked for a tool
    checks = grade(CASE, "Stopped: hit MAX_STEPS without finishing.", run("tool_use", 10))
    assert {"finished", "efficient"} <= failed(checks)


def test_crash_is_not_finished():
    # run() raised before any model call: no stop reason, empty answer
    assert "finished" in failed(grade(CASE, "", run(stop_reason=None, steps=0)))


def test_malformed_url_fails_check_instead_of_crashing():
    answer = "It's 5432, see https://[broken and nothing else."
    assert failed(grade(CASE, answer, run())) == {"trusted_domain"}


def test_wrong_domain_fails():
    answer = "It's 5432 (https://some-blog.example.com/postgres)."
    assert failed(grade(CASE, answer, run())) == {"trusted_domain"}


def test_lookalike_domain_is_not_trusted():
    # "evilpostgresql.org" ends with "postgresql.org" but is a different site
    answer = "It's 5432 (https://evilpostgresql.org/docs)."
    assert failed(grade(CASE, answer, run())) == {"trusted_domain"}


def test_over_step_budget_fails_efficient_only():
    assert failed(grade(CASE, GOOD, run(steps=4))) == {"efficient"}


def test_no_budget_means_no_efficient_check():
    case = {k: v for k, v in CASE.items() if k != "max_steps"}
    assert "efficient" not in grade(case, GOOD, run(steps=50))


def test_not_found_case_needs_no_source():
    case = {"id": "t", "question": "q", "expect": ["could not find"], "require_source": False}
    assert failed(grade(case, "I could not find any record of that.", run())) == set()


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} passed")
