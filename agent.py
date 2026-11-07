# agent.py
# Lesson 2: the agent loop. model -> tool_use? -> run tool -> feed result -> repeat.

import time
from dotenv import load_dotenv
import anthropic
from anthropic.types import MessageParam
from trace import Trace
import memory

load_dotenv()
from tools import TOOLS, REGISTRY
client = anthropic.Anthropic()

SYSTEM = """You are scout, a research assistant.
Search the web, read the most relevant pages, then answer concisely with source URLs.
Do not guess — if you didn't find it, say so."""
MAX_STEPS = 10   # guardrail: never loop forever

def run(question: str) -> str:
    trace = Trace(question)
    past = memory.recall(question)           # earlier runs that share keywords
    trace.log("memory_recall", ids=[m.id for m in past])
    system = SYSTEM + ("\n\n" + memory.as_prompt(past) if past else "")
    messages: list[MessageParam] = [{"role": "user", "content": question}]

    for step in range(MAX_STEPS):
        response = client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=1000,
            system=system,
            tools=TOOLS,
            messages=messages,
        )
        trace.model_call(step, response)

        # always record what the model said (text + tool_use blocks)
        messages.append({"role": "assistant", "content": response.content})

        # done? return the text
        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if b.type == "text")
            trace.finish(answer)
            memory.save(question, answer)    # only finished answers, not MAX_STEPS stops
            return answer

        # otherwise run every tool the model asked for
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"  [step {step+1}] {block.name}({block.input})")
                is_error = False
                t0 = time.time()
                try:
                    model, fn = REGISTRY[block.name]
                    result = fn(model(**block.input))
                except Exception as e:
                    result = f"Error: {type(e).__name__}: {e}"   # model sees it, retries
                    is_error = True
                trace.tool_call(step, block.name, block.input, str(result),
                                (time.time() - t0) * 1000)
                tool_results.append({"type": "tool_result",
                                     "tool_use_id": block.id,
                                     "content": str(result),
                                     "is_error": is_error})

        # results go back as a user message, then loop
        messages.append({"role": "user", "content": tool_results})

    trace.finish("Stopped: hit MAX_STEPS")
    return "Stopped: hit MAX_STEPS without finishing."

if __name__ == "__main__":
    print(run(input("Ask scout: ")))