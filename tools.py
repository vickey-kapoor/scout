# tools.py
# Lesson 4: real tools. search_web finds pages, fetch_page reads one.

import os
import httpx
from bs4 import BeautifulSoup
from tavily import TavilyClient
from models import SearchInput, FetchInput, RecallInput, RememberInput
import memory
from dotenv import load_dotenv
from anthropic.types import ToolParam

load_dotenv()
tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

def search_web(args: SearchInput) -> str:
    """Search the web. Returns titles, URLs and snippets. Use fetch_page to read a result in full."""
    resp = tavily.search(args.query, max_results=args.max_results)
    lines = [f"- {r['title']}\n  {r['url']}\n  {r['content'][:200]}" for r in resp["results"]]
    return "\n".join(lines) or "No results."

def fetch_page(args: FetchInput) -> str:
    """Download a web page and return its readable text (first 8000 chars)."""
    r = httpx.get(args.url, timeout=15, follow_redirects=True,
                  headers={"User-Agent": "scout/0.1"})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()                      # strip noise
    text = " ".join(soup.get_text(" ").split())
    return text[:8000]                       # cap size — context is finite

def recall_memory(args: RecallInput) -> str:
    """Look up what scout already knows or was asked before. Call this FIRST for any question that may have come up previously."""
    return memory.recall(args.query)

def remember(args: RememberInput) -> str:
    """Save a fact worth reusing in future runs. Use for key findings, not trivia."""
    memory.save_fact(args.topic, args.fact, args.source)
    return f"Saved: [{args.topic}] {args.fact}"

REGISTRY = {
    "recall_memory": (RecallInput,   recall_memory),
    "remember":      (RememberInput, remember),
    "search_web":    (SearchInput,   search_web),
    "fetch_page":    (FetchInput,    fetch_page),
}
MEMORY_TOOLS = {"recall_memory", "remember"}   # left out when memory is off (HTTP default)

TOOLS: list[ToolParam] = [
    {"name": n, "description": fn.__doc__, "input_schema": m.model_json_schema()}
    for n, (m, fn) in REGISTRY.items()
]
TOOLS_NO_MEMORY = [t for t in TOOLS if t["name"] not in MEMORY_TOOLS]