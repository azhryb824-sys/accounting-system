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
    tokens = {
        token for token in re.findall(r"[\w\u0600-\u06ff]+", (question or "").lower())
        if len(token) > 2
    }
    if not tokens:
        return []
    with _connect() as connection:
        rows = connection.execute(
            "SELECT topic,title,summary,source_url,source_name,language,updated_at FROM knowledge"
        ).fetchall()
    ranked = []
    for row in rows:
        title = row["title"].lower()
        body = f"{row['topic']} {row['title']} {row['summary']}".lower()
        overlap = sum(3 if token in title else 1 for token in tokens if token in body)
        if overlap:
            ranked.append((overlap, dict(row)))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _score, row in ranked[:limit]]


def status():
    initialize()
    with _connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        latest = connection.execute("SELECT MAX(updated_at) FROM knowledge").fetchone()[0]
    return {"entries": count, "last_updated_at": latest or "", "path": str(STORE_PATH)}

