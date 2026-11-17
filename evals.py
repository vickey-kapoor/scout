# evals.py
# Lesson 7: evals. A fixed set of questions, checked the same way every time,
# so "I changed the prompt and it feels better" becomes a number you can compare.
#
#   python evals.py                    # run every case in evals/cases.jsonl
#   python evals.py austen moon-landing  # run only these case ids
#   EVAL_MIN_PASS=0.8 python evals.py    # exit 1 if under 80% pass (used by CI)
#
# Each run is saved to evals/results/<timestamp>.jsonl, so you can compare
# before and after a change.

import json, os, re, sys, time
from pathlib import Path
from urllib.parse import urlparse

from agent import run
from trace import Trace

CASES = Path("evals/cases.jsonl")
RESULTS_DIR = Path("evals/results")
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def load_cases(only: list[str]) -> list[dict]:
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    return [c for c in cases if not only or c["id"] in only]


def grade(case: dict, answer: str) -> dict[str, bool]:
    """Deterministic checks: cheap, fast, and the same result every time.

    Each check answers one yes/no question about the answer. A case passes only if
    every check passes. Keeping checks separate tells you *what* broke, not just that
    something did.
    """
    urls = URL_RE.findall(answer)
    hosts = [urlparse(u).hostname or "" for u in urls]
    checks = {
        # hit MAX_STEPS, or returned nothing at all
        "finished": bool(answer.strip()) and not answer.startswith("Stopped:"),
        # every expected pattern appears (regex, case-insensitive)
        "correct": all(re.search(p, answer, re.IGNORECASE) for p in case["expect"]),
    }
    # the system prompt asks for source URLs; a "not found" case may skip this
    if case.get("require_source", True):
        checks["cites_source"] = bool(urls)
    # if the case lists trusted domains, at least one cited URL must be on one of them
    if case.get("domains"):
        checks["trusted_domain"] = any(
            h == d or h.endswith("." + d) for h in hosts for d in case["domains"])
    return checks


def run_case(case: dict) -> dict:
    trace = Trace(case["question"])
    t0 = time.time()
    try:
        # memory OFF: otherwise run 2 would just recall run 1's answer, and you'd be
        # measuring the database, not the agent
        answer = run(case["question"], use_memory=False, trace=trace)
        error = None
    except Exception as e:                       # an API error shouldn't stop the suite
        answer, error = "", f"{type(e).__name__}: {e}"
    checks = grade(case, answer)
    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "checks": checks,
        "steps": trace.steps,
        "tools": trace.tools_used,
        "tokens_in": trace.tokens_in,
        "tokens_out": trace.tokens_out,
        "seconds": round(time.time() - t0, 1),
        "error": error,
        "answer": answer,
        "trace": str(trace.path),
    }


def github_summary(results: list[dict]) -> None:
    """In GitHub Actions, write a markdown table to the run's summary page."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    passed = sum(r["passed"] for r in results)
    lines = [f"## scout evals: {passed}/{len(results)} passed\n",
             "| case | result | steps | tokens in | tokens out | failed checks |",
             "|---|---|---|---|---|---|"]
    for r in results:
        failed = ", ".join(k for k, ok in r["checks"].items() if not ok) or ""
        if r["error"]:
            failed += f" ({r['error'][:80]})"
        lines.append(f"| {r['id']} | {'✅' if r['passed'] else '❌'} | {r['steps']} | "
                     f"{r['tokens_in']} | {r['tokens_out']} | {failed} |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def report(results: list[dict]) -> None:
    print(f"\n{'case':<20} {'result':<6} {'steps':>5} {'tok in':>7} {'tok out':>7} {'sec':>5}  failed checks")
    for r in results:
        failed = [k for k, ok in r["checks"].items() if not ok]
        print(f"{r['id']:<20} {'PASS' if r['passed'] else 'FAIL':<6} {r['steps']:>5} "
              f"{r['tokens_in']:>7} {r['tokens_out']:>7} {r['seconds']:>5}  "
              f"{', '.join(failed) or ''}{'  ' + r['error'] if r['error'] else ''}")
    n = len(results)
    passed = sum(r["passed"] for r in results)
    avg = lambda k: sum(r[k] for r in results) / n
    print(f"\n{passed}/{n} passed ({passed / n:.0%})  |  avg {avg('steps'):.1f} steps, "
          f"{avg('tokens_in'):.0f} in / {avg('tokens_out'):.0f} out tokens, {avg('seconds'):.1f}s")


if __name__ == "__main__":
    cases = load_cases(sys.argv[1:])
    if not cases:
        sys.exit("No matching cases.")
    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n=== [{i}/{len(cases)}] {case['id']}: {case['question']}")
        results.append(run_case(case))
    report(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / (time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
    out.write_text("".join(json.dumps(r) + "\n" for r in results))
    print(f"[results] {out}")
    github_summary(results)

    # Model output varies run to run, so CI gates on a pass RATE, not on every case passing.
    min_pass = float(os.environ.get("EVAL_MIN_PASS", "0"))
    rate = sum(r["passed"] for r in results) / len(results)
    if rate < min_pass:
        sys.exit(f"Pass rate {rate:.0%} is below EVAL_MIN_PASS={min_pass:.0%}")
