import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


STORE_PATH = Path(
    os.environ.get("JAMEEL_KNOWLEDGE_DB")
    or Path(__file__).resolve().parent / "data" / "jameel_knowledge.sqlite3"
)
_LOCK = threading.Lock()
_STOP_WORDS = {
    "ما", "ماذا", "من", "هو", "هي", "عن", "في", "على", "إلى", "الى",
    "اشرح", "عرف", "تعريف", "the", "is", "of", "and", "what", "who",
}


def _tokens(text):
    return {
        token
        for token in re.findall(r"[\w\u0600-\u06ff]+", (text or "").lower())
        if len(token) > 2 and token not in _STOP_WORDS
    }


def _connect():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(STORE_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    with _LOCK, _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                source_url TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'ar',
                updated_at TEXT NOT NULL,
                UNIQUE(source_url, title)
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS knowledge_topic_idx ON knowledge(topic)")


def upsert(topic, title, summary, source_url="", source_name="", language="ar"):
    initialize()
    with _LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO knowledge(topic,title,summary,source_url,source_name,language,updated_at)
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source_url,title) DO UPDATE SET
                topic=excluded.topic,
                summary=excluded.summary,
                source_name=excluded.source_name,
                language=excluded.language,
                updated_at=excluded.updated_at
            """,
            (
                topic.strip(),
                title.strip(),
                re.sub(r"\s+", " ", summary).strip()[:4000],
                source_url.strip(),
                source_name.strip(),
                language.strip() or "ar",
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def search(question, limit=4):
    initialize()
    tokens = _tokens(question)
    if not tokens:
        return []
    with _connect() as connection:
        rows = connection.execute(
            "SELECT topic,title,summary,source_url,source_name,language,updated_at FROM knowledge"
        ).fetchall()
    ranked = []
    for row in rows:
        title_tokens = _tokens(row["title"])
        body_tokens = _tokens(f"{row['topic']} {row['title']} {row['summary']}")
        title_overlap = len(tokens & title_tokens)
        body_overlap = len(tokens & body_tokens)
        if len(tokens) == 1:
            relevant = title_overlap == 1
        else:
            required_overlap = max(2, (len(tokens) + 1) // 2)
            relevant = title_overlap > 0 or body_overlap >= required_overlap
        if relevant:
            item = dict(row)
            item["relevance_score"] = title_overlap * 4 + body_overlap
            ranked.append((item["relevance_score"], item))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in ranked[:limit]]


def status():
    initialize()
    with _connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        latest = connection.execute("SELECT MAX(updated_at) FROM knowledge").fetchone()[0]
    return {"entries": count, "last_updated_at": latest or "", "path": str(STORE_PATH)}
