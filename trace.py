# trace.py
# Lesson 5: record every event of a run to traces/<run_id>.jsonl
# so you can replay what the agent saw. One JSON object per line.
# Lesson 8: also totals cache reads/writes, server-side clears and the peak prompt size.

import json, time, uuid
from pathlib import Path
from context import usage_numbers   # Lesson 8: cache + context-editing numbers per call

TRACE_DIR = Path("traces")
TRACE_DIR.mkdir(exist_ok=True)

class Trace:
    def __init__(self, question: str):
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.path = TRACE_DIR / f"{self.run_id}.jsonl"
        self.start = time.time()
        self.tokens_in = self.tokens_out = 0
        self.steps = 0                 # model calls this run (read by evals.py)
        self.tools_used: list[str] = []
        self.stop_reason = None        # of the last model call: "end_turn" = finished normally
        self.cache_read = self.cache_write = 0   # prompt tokens read from / written to the cache
        self.cleared_tokens = 0        # input tokens the API cleared server-side (any edit type)
        self.context_peak = 0          # largest full prompt sent (uncached + cache read + write)
        self.log("run_start", question=question)

    def log(self, event: str, **data):
        record = {"t": round(time.time() - self.start, 3), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def model_call(self, step: int, response):
        n = usage_numbers(response)
        self.steps += 1
        self.stop_reason = response.stop_reason
        self.tokens_in += n["input_tokens"]   # with caching on this is the UNCACHED part only
        self.tokens_out += n["output_tokens"]
        self.cache_read += n["cache_read"]
        self.cache_write += n["cache_write"]
        self.cleared_tokens += n["cleared_tokens"]
        self.context_peak = max(self.context_peak, n["context_tokens"])
        self.log("model_call", step=step, stop_reason=response.stop_reason,
                 input_tokens=n["input_tokens"], output_tokens=n["output_tokens"],
                 cache_read=n["cache_read"], cache_write=n["cache_write"],
                 context_tokens=n["context_tokens"],
                 content=[b.model_dump() for b in response.content])
        if n["edit_types"]:
            self.log("context_edit", step=step, edit_types=n["edit_types"],
                     cleared_tool_uses=n["cleared_tool_uses"], cleared_tokens=n["cleared_tokens"])

    def tool_call(self, step: int, name: str, args: dict, result: str, ms: float):
        self.tools_used.append(name)
        self.log("tool_call", step=step, tool=name, args=args,
                 result_preview=result[:300], result_chars=len(result), ms=round(ms))

    def finish(self, answer: str):
        self.log("run_end", answer=answer, seconds=round(time.time() - self.start, 1),
                 tokens_in=self.tokens_in, tokens_out=self.tokens_out,
                 cache_read=self.cache_read, cache_write=self.cache_write,
                 cleared_tokens=self.cleared_tokens, context_peak=self.context_peak)
        line = (f"\n[trace] {self.path}  |  {self.tokens_in} in / {self.tokens_out} out tokens"
                f"  |  cache {self.cache_read} read / {self.cache_write} written")
        if self.cleared_tokens > 0:
            line += f"  |  cleared {self.cleared_tokens}"
        print(line)
