import re
from urllib.parse import quote

import requests

from knowledge_store import upsert


TOPICS = (
    "mathematics", "physics", "chemistry", "biology", "astronomy", "medicine",
    "engineering", "computer science", "artificial intelligence", "geography",
    "world history", "economics", "finance", "accounting", "Arabic language",
    "English language", "Saudi Arabia", "Palestine international law",
)


def _clean(text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def update(topics=None, limit=2):
    topics = tuple(topics or TOPICS)
    limit = max(1, min(int(limit), 5))
    headers = {"User-Agent": "JameelAI/2.0 independent knowledge updater"}
    processed = 0
    for topic in topics:
        for language in ("ar", "en"):
            try:
                response = requests.get(
                    f"https://{language}.wikipedia.org/w/api.php",
                    params={
                        "action": "query", "list": "search", "srsearch": topic,
                        "srlimit": limit, "format": "json",
                    },
                    headers=headers,
                    timeout=12,
                )
                response.raise_for_status()
                rows = response.json().get("query", {}).get("search", [])
                for row in rows[:limit]:
                    title = row.get("title") or topic
                    summary = _clean(row.get("snippet"))
                    if not summary:
                        continue
                    url = f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                    upsert(topic, title, summary, url, "Wikipedia", language)
                    processed += 1
                if rows:
                    break
            except Exception:
                continue
        try:
            response = requests.get(
                "https://www.wikidata.org/w/api.php",
                params={
                    "action": "wbsearchentities", "search": topic, "language": "ar",
                    "uselang": "ar", "format": "json", "limit": limit,
                },
                headers=headers,
                timeout=12,
            )
            response.raise_for_status()
            for row in response.json().get("search", [])[:limit]:
                entity_id = row.get("id") or ""
                summary = row.get("description") or ""
                if not entity_id or not summary:
                    continue
                upsert(
                    topic,
                    row.get("label") or topic,
                    summary,
                    f"https://www.wikidata.org/wiki/{entity_id}",
                    "Wikidata",
                    "ar",
                )
                processed += 1
        except Exception:
            pass
    return processed


if __name__ == "__main__":
    print(f"Updated {update()} independent Jameel knowledge entries.")
