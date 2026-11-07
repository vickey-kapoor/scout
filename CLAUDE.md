# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

scout is a research agent built from scratch on the Anthropic SDK, deliberately with **no agent framework**. It's a teaching repo: each module starts with a `# Lesson N:` header comment explaining the concept it adds. Keep that style when you add a module, and add the lesson to the README's "Lessons" list. The README is the user-facing doc, so keep its project layout, tools table and Memory section in sync with code changes.

## Commands

Windows dev machine. The user's shell is PowerShell, and the venv is `.venv`.

```powershell
pip install -r requirements.txt          # inside .venv
python agent.py                          # CLI: prompts "Ask scout:", prints [step N] tool calls
uvicorn main:app --reload                # HTTP API on :8000. GET / health, POST /ask {"question": ...}, /docs
python memory.py [query]                 # list recent facts/runs, or show what recall_memory returns
sqlite3 scout.db                         # inspect memory (tables: runs, facts)
```

Keys come from `.env` (`ANTHROPIC_API_KEY`, `TAVILY_API_KEY`); see `.env.example`.

There's **no test suite or linter**. Verify changes with throwaway scripts against a temp database, so the real `scout.db` is untouched:

```bash
SCOUT_MEMORY_DB="$TEMP/test.db" .venv/Scripts/python.exe -c "import agent; print(agent.run('...'))"
```

To test `/ask` without calling the model, use FastAPI `TestClient` and mock `agent.run`. Real `agent.run` calls cost API tokens, so keep them few.

## Architecture

**The loop (`agent.py`).** `run(question, use_memory=True)` sends `messages` plus the tool schemas to `claude-sonnet-5-5`. It runs every `tool_use` block via `REGISTRY` and appends the results as a user turn, then repeats until `stop_reason != "tool_use"`, with a cap of `MAX_STEPS = 10`. A tool exception is returned to the model as an `Error: ...` tool result (`is_error: True`), not raised. The model reads it and retries.

**Tools are generated, not hand-written schemas (`tools.py` + `models.py`).** Each tool is one function plus one `REGISTRY` entry `name: (PydanticInputModel, fn)`. `TOOLS` is built from the registry:
- the **function docstring becomes the tool description the model reads**, so changing a docstring changes agent behaviour;
- `Model.model_json_schema()` becomes the `input_schema`;
- Pydantic validates the model's arguments before the function runs.

**Memory (`memory.py`)** is SQLite (`scout.db`, override with `SCOUT_MEMORY_DB`) with two tables, `runs(question, answer)` and `facts(topic, fact, source)`. The model uses it only through tools:
- `recall_memory` → `memory.recall()`. Any-keyword, whole-word match: `LIKE` narrows the candidates, then a word-boundary regex filters them as the cursor streams, stopping at `limit`. With no match it falls back to the most recent runs, so "what did I ask earlier?" works.
- `remember` → `save_fact()`.
- `agent.run` itself calls `save_run()`, only for `end_turn`, non-empty answers.

**Memory is gated per run.** With `use_memory=False`, `run` uses `SYSTEM_NO_MEMORY` plus `TOOLS_NO_MEMORY`, and refuses `MEMORY_TOOLS` if they're called anyway. `/ask` passes `use_memory=memory_over_http()`, which is **off unless `SCOUT_MEMORY_HTTP=1`**, because memory has no per-caller scoping and would leak research between API callers. Preserve this gating when you touch memory or tools.

**HTTP entry (`main.py`)** must not import `agent` at module load. Importing it (Anthropic SDK, Tavily, bs4) takes about 6s, and that stalled Cloud Run's startup probe until it failed. The FastAPI `lifespan` hook warms `import agent` in a background thread, and `/ask` imports it lazily.

**Tracing (`trace.py`)** writes one JSONL file per run to `traces/<run_id>.jsonl`, logging model calls with token usage and tool calls with timings. Note that `trace.py` shadows the stdlib `trace` module.

### Import-order gotchas
- `agent.py` calls `load_dotenv()` **before** `import memory` / `from tools import ...`. `tools.py` builds the Tavily client at import time, and settings must come from `.env`.
- So env-driven settings are read at call time, not at module import: `SCOUT_MEMORY_DB` in `memory._conn()`, and `SCOUT_MEMORY_HTTP` in `main.memory_over_http()`. Keep it that way; reading at import silently ignores `.env`.

## Deployment (Cloud Run via Terraform in `infra/`)

`infra/README.md` has the full steps. Key facts:
- Private Cloud Run service `scout` (project `propane-cubist-479515-c5`, `us-central1`), invoked with `gcloud auth print-identity-token`. State is local (`infra/terraform.tfstate`, gitignored).
- Secrets: `scout-anthropic-api-key` and `scout-tavily-api-key` in Secret Manager.
- Deploy a new version with a **unique image tag** (the `:latest` tag makes Terraform see no change). Put `image_tag` in `infra/terraform.tfvars` so a plain `apply` doesn't revert it:
  ```powershell
  $tag = git rev-parse --short HEAD
  gcloud builds submit --tag ((terraform -chdir=infra output -raw image) -replace ':latest$', ":$tag") .
  terraform -chdir=infra apply -var "image_tag=$tag"
  ```
- Don't change the service in the Cloud Console. It creates drift from the Terraform config (a Console edit caused a failed revision before).
- Startup probe allows about 125s, and `startup_cpu_boost` is on. Cold start is about 4s now that `agent` is imported in the background.
- `.dockerignore` must keep `.env*`, `*.db` (`scout.db`, the legacy `memory.db`), `traces/` and `infra/` out of the image, because `COPY . .` copies everything else. On Cloud Run, `scout.db` and `traces/` are ephemeral and per-instance.

## Workflow

- Never push to `main`. Every change goes on a branch → `gh pr create` → squash merge.
- Greptile reviews every PR automatically (the "Greptile Review" check plus inline comments, including more comments after each new push). Check its comments with `gh api repos/vickey-kapoor/scout/pulls/<n>/comments`, fix the valid ones, reply on each thread naming the fix commit, and merge only after it passes with no new comments.
- The user normally runs deployments (`terraform apply`, `gcloud builds submit`) themselves. Only run them when explicitly asked in that turn, and apply from a saved `plan -out` file.
