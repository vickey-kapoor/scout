# Working on scout

scout is a learning project: building an agent end to end, from basics to expert, without a
framework. Lessons are numbered (`# Lesson N: ...` header at the top of each file) and listed in
the README. Explain the concept behind a change, not just the change.

## Workflow for coding tasks

Small tasks (one or two files, clear change): do them directly, no pipeline.

Repo-wide or multi-file tasks: work in five steps.

1. **Plan (Fable 5.2):** read the ask and write a step-by-step plan of what to look for and
   change, with concrete search patterns. On large tasks (more than ~5 files, or any change to a
   public interface: the `/ask` API, tool input models, the `evals/cases.jsonl` format), show the
   plan and wait for approval before continuing.
2. **Scan (Haiku):** parallel helpers read the repo and flag spots that match the plan. Use
   Sonnet instead when the search needs reasoning across files. The planner checks scan coverage
   before moving on.
3. **Fix (Sonnet):** one helper per fix, each in its own copy of the code (worktree). Fixes
   touching the same file go to the same helper. If a fix fails its tests twice or spans several
   files, hand it to Opus.
4. **Integrate:** merge all fixes and run tests, build and lint on the combined result. Resolve
   anything that breaks before moving on.
5. **Verify:** Opus checkers independently review every finding and fix and discard wrong ones.
   Then Fable 5.2 reviews what's left against the original ask and signs off before a PR opens.

Never open a PR with failing tests. If a step can't be completed, stop and say what's blocking it.

## Checks for this repo

- Tests: `python test_evals.py` (grader tests, no API keys needed)
- Build: `python -m py_compile *.py`
- Lint: none configured yet; say so rather than inventing one
- Evals: `python evals.py <case ids>` costs real tokens. Locally, run only the cases a change
  affects; the full suite runs in CI on PRs that touch agent code.
