# 01b_chat_loop.py
# Lesson 1b: multi-turn chat. The messages list IS the memory.

from dotenv import load_dotenv
import anthropic

load_dotenv()
client = anthropic.Anthropic()

messages = []   # conversation history, grows every turn

while True:
    user_input = input("You: ")
    if user_input.strip().lower() in ("quit", "exit"):
        break

    # 1. add what the user said
    messages.append({"role": "user", "content": user_input})

    # 2. send the ENTIRE history — the model is stateless
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=500,
        system="You are scout, a concise research assistant.",
        messages=messages,
    )
    reply = "".join(block.text for block in response.content if block.type == "text")
    print("scout:", reply)

    # 3. add what the model said, so next turn it remembers
    # messages.append({"role": "assistant", "content": reply})