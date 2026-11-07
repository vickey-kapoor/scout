# models.py
# Lesson 3: Pydantic models define tool inputs ONCE. They validate the
# model's arguments and generate the JSON schema the model reads.

from pydantic import BaseModel, Field

class SearchInput(BaseModel):
    query: str = Field(description="What to search the web for")
    max_results: int = Field(default=5, ge=1, le=10, description="How many results")

class FetchInput(BaseModel):
    url: str = Field(description="Full URL to read, starting with http")
class RecallInput(BaseModel):
    query: str = Field(description="Keyword or topic to look up in memory")

class RememberInput(BaseModel):
    topic: str = Field(description="Short topic label, e.g. 'LangGraph'")
    fact: str = Field(description="One self-contained fact worth reusing later")
    source: str = Field(default="", description="URL the fact came from, if any")
