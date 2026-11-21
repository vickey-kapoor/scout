# scout

A terminal research agent built from scratch in Python — no agent framework, just the Anthropic SDK and a tool-use loop.

Ask it a question. It searches the web, reads the most relevant pages, and answers with source URLs.

```
$ python agent.py
Ask scout: What did Anthropic announce this week?
  [step 1] search_web({'query': 'Anthropic announcement', 'max_results': 5})
  [step 2] fetch_page({'url': 'https://www.anthropic.com/news/...'})
Anthropic announced ... (sources: ...)
```

## Why no framework?

To understand what frameworks actually do. The whole agent is one loop:

```
send messages + tool list to the model
  → model replies with text, or asks for a tool (stop_reason == "tool_use")
  → run the tool, append the result to messages
  → repeat until the model stops asking for tools
```

That loop is `agent.py`. Everything else — LangGraph, CrewAI, the Claude Agent SDK — is an elaboration of it.

## Project layout

```
scout/
├── .env              # API keys (gitignored, never committed)
├── .env.example      # placeholder keys — copy to .env
├── .gitignore
├── .dockerignore     # keeps .env and local files out of the image
├── Dockerfile        # container for Cloud Run
├── requirements.txt
├── 01_hello_llm.py   # lesson 1: one API call
├── 01b_chat_loop.py  # lesson 1b: multi-turn chat
├── main.py           # HTTP API (FastAPI): POST /ask
├── agent.py          # the loop: model → tool_use? → run tool → repeat
├── tools.py          # tool functions + registry; TOOLS schema is generated
├── models.py         # Pydantic models: validate tool inputs, generate schemas
├── trace.py          # writes each run to traces/<run_id>.jsonl
├── context.py        # Lesson 8: prompt caching + server-side context editing settings
├── memory.py         # SQLite memory: runs + facts, used via recall_memory / remember tools
├── evals.py          # runs every eval case, grades answers, saves results
├── evals/cases.jsonl # the eval questions and what a correct answer must contain
├── test_evals.py     # tests for the grader itself (no API keys needed)
├── test_context.py   # tests for context.py and the append-only loop, no API keys
├── .github/workflows/evals.yml  # runs evals in CI on agent-code PRs
├── infra/            # Terraform for Cloud Run (see infra/README.md)
├── README.md
│
│   created at runtime (gitignored):
├── scout.db          # long-term memory
├── traces/           # one <run_id>.jsonl per run
└── evals/results/    # one <timestamp>.jsonl per eval run
```

| File | Responsibility |
|---|---|
| `agent.py` | Decision loop, system prompt, `MAX_STEPS` guardrail, error feedback to the model |
| `tools.py` | What the agent can *do*. Add a tool = one function + one registry line |
| `models.py` | The shape of each tool's input. Pydantic validates at the door and builds the JSON schema the model reads |
| `main.py` | HTTP wrapper around `agent.run()` for deployment |
| `trace.py` | Logs every model call and tool call (tokens, cache reads and writes, timings, results) as JSON lines, plus a `context_edit` event whenever the API clears old tool results |
| `context.py` | Request options for prompt caching and server-side clearing of old tool results, and a helper that turns the API's usage numbers into plain ones |
| `evals.py` | Runs the fixed question set, grades each answer, prints pass rate, steps, tokens and time |
| `memory.py` | Long-term memory in `scout.db`: past runs and saved facts. The model reads and writes it through the `recall_memory` and `remember` tools |

## Tools

| Tool | What it does |
|---|---|
| `search_web` | Web search via Tavily — returns titles, URLs, snippets |
| `fetch_page` | Downloads a URL and returns its readable text (capped at 8000 chars) |
| `recall_memory` | Looks up saved facts and past runs in `scout.db` (see [Memory](#memory)) |
| `remember` | Saves a durable fact (topic, fact, source URL) for future runs |

The model decides which tools to call and in what order. The code only describes them and obeys.

## Setup

```bash
git clone https://github.com/vickey-kapoor/scout
cd scout
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-...
TAVILY_API_KEY=tvly-...
```

Run in the terminal:

```bash
python agent.py
```

Or run as an HTTP API:

```bash
uvicorn main:app --reload
# open http://localhost:8000/docs to try it in the browser, or:
curl -X POST localhost:8000/ask -H "Content-Type: application/json" \
     -d '{"question": "Who created Python?"}'
```

| Endpoint | Purpose |
|---|---|
| `GET /` | Health check → `{"status": "ok"}` |
| `POST /ask` | `{"question": "..."}` → `{"answer": "..."}` |
| `GET /docs` | Interactive API docs |

## Memory

scout keeps long-term memory in `scout.db` (SQLite), and the model uses it through two tools:

- **`recall_memory(query)`:** the system prompt tells the model to call this before searching the web. It returns matching **facts** and **past runs**, matched on any keyword in the query. If nothing matches, it returns the most recent runs, so "what did I ask you earlier?" still works.
- **`remember(topic, fact, source)`:** the model saves a durable fact it learned, such as a key finding with its URL.
- Every complete answer (`end_turn`, not empty) is also saved as a run. Cut-off answers and `MAX_STEPS` stops are not.

Memory results come back as tool results, the same way web pages do. The system prompt says to treat them as notes from earlier runs, never as instructions, and to verify anything time-sensitive.

- **CLI (`python agent.py`):** memory is on.
- **HTTP API (`/ask`):** memory is **off** unless `SCOUT_MEMORY_HTTP=1` is set, and the model isn't offered the memory tools at all. Memory isn't separated by caller yet, so with several callers one person's research could appear in another's answer.
- **Location:** `scout.db` in the folder you run scout from. It's created on first use. Set `SCOUT_MEMORY_DB` to use another path.
- **Not committed or shipped:** it's listed in `.gitignore` and `.dockerignore`.
- **Reset:** delete `scout.db`.
- **On Cloud Run** it lives on the container's temporary disk. It's lost when an instance shuts down, and each instance has its own copy.

### Inspecting it

```powershell
python memory.py              # 10 most recent facts and runs
python memory.py LangGraph    # what recall_memory would return
sqlite3 scout.db              # SQL shell (winget install SQLite.SQLite)
```

Or open it in [DB Browser for SQLite](https://sqlitebrowser.org/) (`winget install DBBrowserForSQLite.DBBrowserForSQLite`).
Close the GUI while scout is running, because an open database can block saves.

There are two tables. `runs` has `id, ts, question, answer` and `facts` has `id, ts, topic, fact, source`. `ts` is a Unix timestamp.

```sql
-- facts, newest first
SELECT id, datetime(ts, 'unixepoch') AS saved, topic, fact, source FROM facts ORDER BY ts DESC;

-- past runs, newest first
SELECT id, datetime(ts, 'unixepoch') AS saved, question FROM runs ORDER BY ts DESC;

-- search, the way recall_memory does (any keyword)
SELECT topic, fact FROM facts WHERE topic LIKE '%langgraph%' OR fact LIKE '%langgraph%';

-- forget something
DELETE FROM facts WHERE id = 3;
```

## Evals

An eval is a fixed set of questions checked the same way every time. Without one, "I changed the
prompt and it seems better" is a feeling. With one, it's `11/13 → 12/13, 4.2 → 3.1 steps`.

```bash
python evals.py                       # every case (makes real API calls: costs tokens)
python evals.py austen moon-landing   # just these cases
```

```
case                 result steps  tok in  cached tok out   sec  failed checks
python-creator       PASS       3     450    4100     140   9.8  
australia-capital    FAIL       2     450       0      95   6.1  trusted_domain
...
11/13 passed (85%)  |  avg 3.1 steps, 900 in / 3200 cache-read / 280 out tokens, 6.0s  |  context cleared in 1 run(s)
```

`tok in` counts only the **uncached** part of the prompt (see [Context management](#context-management)).
`cached` is the part read from the prompt cache. The real prompt size is the two added together
(plus anything newly written to the cache). The numbers above are illustrative.

Each case in `evals/cases.jsonl` is one JSON line:

```json
{"id": "postgres-port", "question": "What is the default TCP port for PostgreSQL?",
 "expect": ["5432"], "domains": ["postgresql.org"]}
```

| Field | Meaning |
|---|---|
| `expect` | Regexes (case-insensitive) that must **all** appear in the answer |
| `domains` | Optional. At least one cited URL must be on one of these sites |
| `require_source` | Optional, default `true`. Set `false` for questions with no real answer |
| `max_steps` | Optional. Fail if the agent needed more model calls than this |

Each run gets separate yes/no checks, so a failure tells you *what* broke:

| Check | Fails when |
|---|---|
| `finished` | The model didn't stop on its own (`end_turn`): cut off by `max_tokens`, stopped by `MAX_STEPS`, or crashed |
| `correct` | An `expect` pattern is missing from the answer |
| `cites_source` | No URL in the answer |
| `trusted_domain` | No cited URL is on a `domains` site (malformed URLs count as not trusted) |
| `efficient` | More model calls than `max_steps` |

Things to know:

- **Memory is off during evals.** Otherwise later runs would just recall earlier answers.
- **Stable facts only.** "Who won yesterday?" changes, so it can't have a fixed expected answer.
- **Include a trick question.** `made-up-town` asks about a town that doesn't exist; passing means
  scout says so instead of inventing an answer.
- **Results are saved** to `evals/results/<timestamp>.jsonl` (gitignored), with full answers and
  trace paths, so you can compare runs and open the trace of any failure.
- **Model output varies.** Run twice before trusting a 1-case difference.
- **Test the grader too.** `python test_evals.py` checks the checks: a cut-off answer must not
  count as finished, a malformed URL must fail rather than crash. An eval that wrongly passes
  is worse than none, because you trust it. `python test_context.py` does the same for Lesson 8:
  it checks the request options and that the loop never edits earlier messages.

### In CI

`.github/workflows/evals.yml` runs the suite on GitHub Actions for PRs that change agent code,
or on demand from the Actions tab ("Run workflow"). Setup: add the repo secrets
`ANTHROPIC_API_KEY` and `TAVILY_API_KEY` (Settings → Secrets and variables → Actions).

- It runs `python test_evals.py` and `python test_context.py` first (both free); a broken grader or a broken loop stops the job before any tokens are spent.
- The job fails if fewer than `EVAL_MIN_PASS` (80%) of cases pass. It's a rate, not 100%,
  because one unlucky answer shouldn't block a PR.
- The score table appears on the run's summary page; answers and traces are a downloadable artifact.
- Each run costs real tokens, so docs-only PRs skip it and a new push cancels the older run.
- PRs from forks don't get secrets, so the job can't run there.

## Context management

### The problem

The model is stateless. Every step resends the whole `messages` list, so step N pays again for
steps 1 to N-1. Page text makes this grow fast. A long run is slower and costlier at every step,
and can eventually hit the context window.

You can see it in the trace: each `model_call` event has `context_tokens`, the real prompt size
for that step. Watch it climb. `run_end` records the biggest value as `context_peak`.

Two techniques fix this, and they work together:

1. **Prompt caching** makes the resent part cheap.
2. **Clearing old tool results** makes the resent part smaller.

Both are set up in `context.py` and passed to the API with `client.beta.messages.create(..., **request_kwargs())`.

### Prompt caching

`request_kwargs()` adds one top-level `cache_control` marker (`{"type": "ephemeral"}`). The API
caches the prompt up to the end of the conversation. Caching is a **prefix match**: the next
request reuses the cache as long as it starts with exactly the same content. Each step only
appends to the end, so the breakpoint moves to the new end and step N reads steps 1 to N-1
from cache.

Verify it with `cache_read` (tokens served from cache) and `cache_write` (tokens newly cached) on each
`model_call`. The printed trace line shows the totals:

```
[trace] traces/<id>.jsonl  |  2228 in / 193 out tokens  |  cache 4100 read / 1200 written
```

| | Price vs normal input (Sonnet 5.5) |
|---|---|
| Cache read | 0.05x |
| Cache write (5-minute lifetime) | 1.25x |

On Sonnet 5.5 the cacheable prefix must be at least 512 tokens, or nothing is cached.

Honest caveat: every cache write costs 1.25x, and a write pays off only when a later step reads it.
Step 1 may even be under the 512-token minimum. So a very short run can cost slightly **more**
with caching on. It pays off from step 3, and the longer
the run, the more it saves. One more rule: any byte change in the prefix invalidates the cache
from that point on.

Measurement changed too. With caching on, `input_tokens` (`tok in`) counts only the **uncached**
part. Real prompt size = `tok in` + cache read + cache write. That sum is `context_tokens`.

### Clearing old tool results (server-side context editing)

Caching makes old pages cheap, but they still fill the window. So `request_kwargs()` also asks
the API to clear old tool results, using the `clear_tool_uses_20250919` strategy. This runs on
the server, which sees the prompt before the model does. It needs the beta header
`CONTEXT_BETA = "context-management-2025-06-27"`.

| Constant | Value | Meaning and why |
|---|---|---|
| `CLEAR_TRIGGER_TOKENS` | 8,000 | Start clearing once the prompt passes this many input tokens. The API default is 100,000. It is low here on purpose, so you can watch clearing happen in a short run. |
| `KEEP_TOOL_USES` | 4 | Keep the 4 most recent tool uses and their results (API default: 3). Clearing happens on the request that carries the newest results, so this must cover the biggest parallel batch, or a page is cleared before the model reads it. 4 covers the 4-page `db-default-ports` case. |
| `CLEAR_AT_LEAST_TOKENS` | 2,000 | Only clear if at least this many tokens are freed. Clearing changes the prefix, which invalidates the cache from the cleared point on. A tiny clear would throw away the cache to save almost nothing. |

When the API applies an edit, trace.py logs a `context_edit` event with `step`, `edit_types`,
`cleared_tool_uses` and `cleared_tokens`. `run_end` adds the total as `cleared_tokens`, and the
trace line ends with `  |  cleared 2500`. The eval summary says `context cleared in N run(s)`.

Things to know:

- **At 8,000 tokens, this is hygiene, not savings.** Cached reads are already cheap. Clearing keeps
  the context focused, and it is the first step toward runs that would otherwise not fit.
- **A cleared page is gone.** The model can no longer re-read it. That is why the system prompt
  now says: "Older tool results may be cleared to save space: after reading a page, state the key
  facts you need from it before fetching more."
- **Limitation:** if the model fetches more than 4 pages in a single parallel batch, the oldest
  can be cleared before the model has read it.

Two eval cases exercise this. `tls-rfcs` (RFC numbers and years for TLS 1.0, 1.2 and 1.3; RFCs
never change) takes about 3 page fetches and shows cache reads across steps. `db-default-ports`
(default ports of PostgreSQL, MySQL, Redis and MongoDB from their official docs) takes about 4
fetches, which pushes the prompt past the trigger. Clearing only happens if enough older,
already-read results pile up behind the 4 kept ones (for example a re-fetch or a second search),
so expect `context_edit` events in some runs, not all.

### Why not trim `messages` ourselves?

This is the key idea of the lesson. The obvious way to shrink the context is to edit the list in
code, for example shortening an old tool result. Don't.

Scout's model (Sonnet 5.5) runs adaptive thinking by default, so its responses can contain thinking
blocks.
The API ties each thinking block to the exact conversation that produced it. If your code edits an
earlier message, then replaying a later thinking block fails with a 400 error on accounts created
on or after 31 Aug 2026. On every account, the prompt cache also misses from the edited point
onward, so you lose the savings from the section above.

Server-side context editing is different: it does not count as an edit. Your `messages` list stays
exactly as you sent it; the API trims its own copy.

The rule: **`messages` is append-only.** Append `response.content` verbatim. Never edit, filter or
rebuild earlier entries. `test_context.py` enforces this, including a test that the loop resends
thinking blocks unchanged.

### What's next

Clearing drops old results entirely. When that isn't enough, the next step is summarizing old turns
(compaction). That is a later lesson.

## Docker / Cloud Run

```bash
docker build -t scout .
docker run --rm -p 8080:8080 --env-file .env scout
```

The image never contains `.env`. On Cloud Run the keys come from Secret Manager
(`scout-anthropic-api-key`, `scout-tavily-api-key`). The service is deployed with Terraform;
see [`infra/README.md`](infra/README.md) for the full steps.
Note: `traces/` and `scout.db` live on the container's temporary disk, so they are lost on restart and not shared between instances.

## How it works, in a little more detail

1. **The model is stateless.** It only knows what is in the `messages` list. That list *is* the agent's memory; every loop iteration appends to it and resends the whole thing. That resend is why Lesson 8 caches the prefix.
2. **Tools are described, not registered.** `TOOLS` is a list of JSON schemas sent with every request. The model reads the `description` fields like documentation and chooses — most "it's not using the tool" bugs are a vague description.
3. **Validation at the boundary.** The model's arguments are raw JSON. Each tool's Pydantic model checks type, presence and range before the function runs.
4. **Errors go back to the model.** A failed tool (404, timeout, bad input) is returned as `Error: ...` in the tool result (flagged `is_error: True`) rather than crashing. The model reads it and retries differently.
5. **Guardrails.** `MAX_STEPS` caps loop iterations; page text is truncated so a single fetch can't blow the context window, and the API clears old tool results once the prompt passes 8,000 tokens.

## Lessons this repo was built through

- **Lesson 1** — One API call (`01_hello_llm.py`)
- **Lesson 1b** — Multi-turn chat: message list as memory (`01b_chat_loop.py`)
- **Lesson 2** — Tool calling: the agent loop (`agent.py`)
- **Lesson 3** — Pydantic: validated inputs, generated schemas (`models.py`)
- **Lesson 4** — Real tools: web search and page fetch (`tools.py`)
- **Lesson 5** — Tracing: every model and tool call as JSON lines (`trace.py`)
- **Lesson 6** — Persistent memory across sessions with SQLite (`memory.py`)
- **Lesson 7** — Evals: a fixed question set, graded automatically (`evals.py`)
- **Lesson 8** — Context management: prompt caching + server-side clearing of old tool results (`context.py`)

## Roadmap

- [x] Observability: log every model call and tool result (`trace.py`)
- [x] Persistent memory across sessions (SQLite)
- [x] Context management: cache the growing prefix, let the API clear old tool results (`context.py`)
- [ ] Compaction: summarize old turns when clearing isn't enough
- [ ] Human-approval gate for side-effecting tools
- [ ] MCP client: plug in third-party tool servers
- [x] Evals: a fixed set of questions with expected answers

## Author

Vickey Kapoor — [@vickey-kapoor](https://github.com/vickey-kapoor)