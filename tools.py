# tools.py
# Lesson 4: real tools. search_web finds pages, fetch_page reads one.

import os
import httpx
from bs4 import BeautifulSoup
from tavily import TavilyClient
from models import SearchInput, FetchInput
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

REGISTRY = {
    "search_web":  (SearchInput,  search_web),
    "fetch_page":  (FetchInput,   fetch_page),
}

TOOLS: list[ToolParam] = [
    {"name": n, "description": fn.__doc__, "input_schema": m.model_json_schema()}
    for n, (m, fn) in REGISTRY.items()
]