# memory.py
# Lesson 6: persistent memory across sessions. The messages list is memory for ONE
# run; this keeps finished answers in SQLite so later runs can build on them.
#
#   save(question, answer)   -> store a finished run
#   recall(question)         -> past runs that share keywords (full-text search, BM25)
#   as_prompt(memories)      -> text block to append to the system prompt
#
# No embeddings: SQLite's built-in FTS5 does keyword search with BM25 ranking, which
# is enough to find "I researched this before". Swap in vector search later if needed.

import os
import re
import sqlite3
import time
from dataclasses import dataclass

DB_PATH = os.environ.get("SCOUT_MEMORY_DB", "memory.db")
MAX_ANSWER_CHARS = 1500   # per recalled memory: enough to reuse, not enough to flood context


@dataclass
class Memory:
    id: int
    created: str
    question: str
    answer: str


def _connect() -> sqlite3.Connection:
    # a fresh connection per call: simple, and safe when FastAPI runs requests in threads
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id       INTEGER PRIMARY KEY,
            created  TEXT NOT NULL,
            question TEXT NOT NULL,
            answer   TEXT NOT NULL
        );
        -- search index over the same rows (external-content FTS5 table)
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(question, answer, content='memories', content_rowid='id');
        CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, question, answer)
            VALUES (new.id, new.question, new.answer);
        END;
    """)
    return conn


def save(question: str, answer: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO memories (created, question, answer) VALUES (?, ?, ?)",
            (time.strftime("%Y-%m-%d %H:%M"), question, answer),
        )
    conn.close()


def _fts_query(text: str) -> str:
    # "What's new in Python 3.14?" -> "whats" OR "new" OR "python" OR "3" ...
    # each word is quoted so punctuation/keywords can't break FTS5 query syntax
    words = {w for w in re.findall(r"\w+", text.lower()) if len(w) > 2}
    return " OR ".join(f'"{w}"' for w in sorted(words))


def recall(question: str, k: int = 3) -> list[Memory]:
    query = _fts_query(question)
    if not query:
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT m.id, m.created, m.question, m.answer
               FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid
               WHERE memories_fts MATCH ?
               ORDER BY bm25(memories_fts) LIMIT ?""",
            (query, k),
        ).fetchall()
    finally:
        conn.close()
    return [Memory(*r) for r in rows]


def as_prompt(memories: list[Memory]) -> str:
    if not memories:
        return ""
    parts = [
        "Notes from your earlier research. They may be outdated or only loosely related: "
        "use them as a starting point, and verify anything time-sensitive with a fresh search."
    ]
    for m in memories:
        parts.append(f"[{m.created}] Q: {m.question}\nA: {m.answer[:MAX_ANSWER_CHARS]}")
    return "\n\n".join(parts)


if __name__ == "__main__":
    # python memory.py            -> list recent memories
    # python memory.py <question> -> show what recall() would return
    import sys
    if len(sys.argv) > 1:
        found = recall(" ".join(sys.argv[1:]))
    else:
        conn = _connect()
        found = [Memory(*r) for r in conn.execute(
            "SELECT id, created, question, answer FROM memories ORDER BY id DESC LIMIT 10")]
        conn.close()
    for m in found:
        print(f"#{m.id} [{m.created}] {m.question}\n    {m.answer[:150]!r}")
    if not found:
        print("(no memories)")
