# 01_hello_llm.py
# Lesson 1: one call to the model. Proves the SDK + API key work.

from dotenv import load_dotenv   # reads .env into environment variables
import anthropic

load_dotenv()                    # must run before creating the client

client = anthropic.Anthropic()   # picks up ANTHROPIC_API_KEY from env

response = client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=300,
    system="You are scout, a concise research assistant.",
    messages=[
        {"role": "user", "content": "In one sentence, what does an AI agent do?"}
    ],
)

print(response.content[0].text)