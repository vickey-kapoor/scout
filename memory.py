# memory.py
# Lesson 6: long-term memory in SQLite. Survives between runs.
# Two tables: runs (what was asked/answered) and facts (things worth reusing).
# The model reads and writes memory through two tools (see tools.py):
#   recall_memory -> recall()     remember -> save_fact()
# and agent.py calls save_run() after every completed answer.

import os, re, sqlite3, time

# common words that would match almost everything; short topics like "go", "ai", "r" are kept
STOPWORDS = set("""
a an and are as at be by can did do does for from has have how i in is it its me my of on or
s that the this to was were what when where which who why will with you your about
""".split())


def _conn() -> sqlite3.Connection:
    # path read per call, so SCOUT_MEMORY_DB set in .env (loaded after import) still applies
    conn = sqlite3.connect(os.environ.get("SCOUT_MEMORY_DB", "scout.db"))
    conn.execute("""CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY, ts REAL, question TEXT, answer TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY, ts REAL, topic TEXT, fact TEXT, source TEXT)""")
    return conn


def _run(sql: str, params: tuple = ()) -> list[tuple]:
    conn = _conn()
    try:
        with conn:                      # commits on success
            return conn.execute(sql, params).fetchall()
    finally:
        conn.close()                    # `with conn` alone doesn't close it


def save_run(question: str, answer: str) -> None:
    _run("INSERT INTO runs (ts, question, answer) VALUES (?, ?, ?)",
         (time.time(), question, answer))


def save_fact(topic: str, fact: str, source: str = "") -> None:
    _run("INSERT INTO facts (ts, topic, fact, source) VALUES (?, ?, ?, ?)",
         (time.time(), topic, fact, source))


def _keyword_filter(columns: tuple[str, str], query: str) -> tuple[str, list[str]]:
    # "LangGraph agents" -> (topic LIKE '%langgraph%' OR fact LIKE '%langgraph%' OR ... agents ...)
    # matching ANY keyword, so a multi-word query still finds a row that has one of them
    words = [w for w in re.findall(r"\w+", query.lower()) if w not in STOPWORDS] or [query]
    clauses, params = [], []
    for w in words:
        for col in columns:
            clauses.append(f"{col} LIKE ?")
            params.append(f"%{w}%")
    return "(" + " OR ".join(clauses) + ")", params


def recall(query: str, limit: int = 5) -> str:
    """Keyword search over past runs and facts. Returns a text block for the model."""
    where, p = _keyword_filter(("topic", "fact"), query)
    facts = _run(f"SELECT topic, fact, source FROM facts WHERE {where} "
                 "ORDER BY ts DESC LIMIT ?", (*p, limit))
    where, p = _keyword_filter(("question", "answer"), query)
    runs = _run(f"SELECT question, answer FROM runs WHERE {where} "
                "ORDER BY ts DESC LIMIT ?", (*p, limit))
    out = []
    for topic, fact, source in facts:
        out.append(f"FACT [{topic}]: {fact}" + (f" (source: {source})" if source else ""))
    for q, a in runs:
        out.append(f"PAST RUN — Q: {q}\n  A: {a[:300]}")
    if out:
        return "\n".join(out)
    # No keyword match. Questions like "what did I ask earlier?" share no keywords with the
    # earlier run, so show the most recent runs instead of nothing.
    recent = _run("SELECT question, answer FROM runs ORDER BY ts DESC LIMIT ?", (limit,))
    if not recent:
        return "Nothing in memory about that."
    return "No match for that query. Most recent runs:\n" + "\n".join(
        f"PAST RUN — Q: {q}\n  A: {a[:300]}" for q, a in recent)


if __name__ == "__main__":
    # python memory.py          -> recent facts and runs
    # python memory.py <query>  -> what recall_memory would return
    import sys
    if len(sys.argv) > 1:
        print(recall(" ".join(sys.argv[1:])))
    else:
        for topic, fact in _run("SELECT topic, fact FROM facts ORDER BY ts DESC LIMIT 10"):
            print(f"FACT [{topic}] {fact}")
        for q, a in _run("SELECT question, answer FROM runs ORDER BY ts DESC LIMIT 10"):
            print(f"RUN  {q}\n     {a[:120]!r}")
