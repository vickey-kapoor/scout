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
└── README.md
```

| File | Responsibility |
|---|---|
| `agent.py` | Decision loop, system prompt, `MAX_STEPS` guardrail, error feedback to the model |
| `tools.py` | What the agent can *do*. Add a tool = one function + one registry line |
| `models.py` | The shape of each tool's input. Pydantic validates at the door and builds the JSON schema the model reads |
| `main.py` | HTTP wrapper around `agent.run()` for deployment |
| `trace.py` | Logs every model call and tool call (tokens, timings, results) as JSON lines |

## Tools

| Tool | What it does |
|---|---|
| `search_web` | Web search via Tavily — returns titles, URLs, snippets |
| `fetch_page` | Downloads a URL and returns its readable text (capped at 8000 chars) |

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

## Docker / Cloud Run

```bash
docker build -t scout .
docker run --rm -p 8080:8080 --env-file .env scout
```

The image never contains `.env`. On Cloud Run the keys come from Secret Manager
(`scout-anthropic-api-key`, `scout-tavily-api-key`). The service is deployed with Terraform;
see [`infra/README.md`](infra/README.md) for the full steps.
Note: `traces/` lives on the container's temporary disk and is lost on restart.

## How it works, in a little more detail

1. **The model is stateless.** It only knows what is in the `messages` list. That list *is* the agent's memory; every loop iteration appends to it and resends the whole thing.
2. **Tools are described, not registered.** `TOOLS` is a list of JSON schemas sent with every request. The model reads the `description` fields like documentation and chooses — most "it's not using the tool" bugs are a vague description.
3. **Validation at the boundary.** The model's arguments are raw JSON. Each tool's Pydantic model checks type, presence and range before the function runs.
4. **Errors go back to the model.** A failed tool (404, timeout, bad input) is returned as `Error: ...` in the tool result (flagged `is_error: True`) rather than crashing. The model reads it and retries differently.
5. **Guardrails.** `MAX_STEPS` caps loop iterations; page text is truncated so a single fetch can't blow the context window.

## Lessons this repo was built through

- **Lesson 1** — One API call (`01_hello_llm.py`)
- **Lesson 1b** — Multi-turn chat: message list as memory (`01b_chat_loop.py`)
- **Lesson 2** — Tool calling: the agent loop (`agent.py`)
- **Lesson 3** — Pydantic: validated inputs, generated schemas (`models.py`)
- **Lesson 4** — Real tools: web search and page fetch (`tools.py`)

## Roadmap

- [ ] Observability: log every model call and tool result
- [ ] Persistent memory across sessions (SQLite)
- [ ] Context management: summarize when the message list gets long
- [ ] Human-approval gate for side-effecting tools
- [ ] MCP client: plug in third-party tool servers
- [ ] Evals: a fixed set of questions with expected answers

## Author

Vickey Kapoor — [@vickey-kapoor](https://github.com/vickey-kapoor)