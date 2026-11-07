# main.py
# HTTP entry point for deployment (e.g. Cloud Run).
# Local:  uvicorn main:app --reload   then open http://localhost:8000/docs

import importlib
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

# `agent` pulls in the Anthropic SDK, Tavily, bs4... (~6s of imports). Importing it at
# module load kept uvicorn from listening, so Cloud Run's startup probe waited on it.
# Instead, start listening right away and warm the import in a background thread.
# /ask imports it too; Python's import lock makes that wait for the warm-up if needed.


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=importlib.import_module, args=("agent",), daemon=True).start()
    yield


# Memory is shared by everyone who can call the API (no per-caller scoping yet), so one
# caller's research could surface in another's answer. Off over HTTP unless opted in
# with SCOUT_MEMORY_HTTP=1. Read per request (below), after `agent` has run
# load_dotenv(), so the setting also works when it comes from .env.
def memory_over_http() -> bool:
    return os.environ.get("SCOUT_MEMORY_HTTP") == "1"

app = FastAPI(
    title="scout",
    description="Research agent: searches the web and answers with sources.",
    lifespan=lifespan,
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, description="What to research")


class AskResponse(BaseModel):
    answer: str


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask")
def ask(req: AskRequest) -> AskResponse:
    # plain `def` (not async): run() blocks, so FastAPI runs it in a worker thread
    from agent import run

    return AskResponse(answer=run(req.question, use_memory=memory_over_http()))
