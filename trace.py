# trace.py
# Lesson 5: record every event of a run to traces/<run_id>.jsonl
# so you can replay what the agent saw. One JSON object per line.

import json, time, uuid
from pathlib import Path

TRACE_DIR = Path("traces")
TRACE_DIR.mkdir(exist_ok=True)

class Trace:
    def __init__(self, question: str):
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.path = TRACE_DIR / f"{self.run_id}.jsonl"
        self.start = time.time()
        self.tokens_in = self.tokens_out = 0
        self.log("run_start", question=question)

    def log(self, event: str, **data):
        record = {"t": round(time.time() - self.start, 3), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def model_call(self, step: int, response):
        u = response.usage
        self.tokens_in += u.input_tokens
        self.tokens_out += u.output_tokens
        self.log("model_call", step=step, stop_reason=response.stop_reason,
                 input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                 content=[b.model_dump() for b in response.content])

    def tool_call(self, step: int, name: str, args: dict, result: str, ms: float):
        self.log("tool_call", step=step, tool=name, args=args,
                 result_preview=result[:300], result_chars=len(result), ms=round(ms))

    def finish(self, answer: str):
        self.log("run_end", answer=answer, seconds=round(time.time() - self.start, 1),
                 tokens_in=self.tokens_in, tokens_out=self.tokens_out)
        print(f"\n[trace] {self.path}  |  {self.tokens_in} in / {self.tokens_out} out tokens")