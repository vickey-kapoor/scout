# main.py
# HTTP entry point for deployment (e.g. Cloud Run).
# Local:  uvicorn main:app --reload   then open http://localhost:8000/docs

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent import run

app = FastAPI(title="scout", description="Research agent: searches the web and answers with sources.")


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
    return AskResponse(answer=run(req.question))
