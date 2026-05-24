import re

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from invoicing.ai_services import ZATCA_OFFICIAL_REGULATIONS, upsert_ai_knowledge_entry
from invoicing.models import AIKnowledgeSource


DEFAULT_TOPICS = (
    "accounting",
    "cash flow",
    "inventory management",
    "project management",
    "small business Saudi Arabia",
)


def _clean_text(text, limit=900):
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    return clean[:limit]


class Command(BaseCommand):
    help = "Update the AI knowledge base from configured free and official internet sources."

    def add_arguments(self, parser):
        parser.add_argument("--topic", action="append", dest="topics", help="Extra public knowledge topic to fetch.")

    def handle(self, *args, **options):
        created_or_updated = 0
        now = timezone.now()

        for item in ZATCA_OFFICIAL_REGULATIONS:
            source, _ = AIKnowledgeSource.objects.update_or_create(
                url=item["url"],
                defaults={
                    "name": item["title"],
                    "license_note": "Official ZATCA public regulation page; verify latest text at source.",
                    "is_active": True,
                    "last_checked_at": now,
                    "last_error": "",
                },
            )
            upsert_ai_knowledge_entry(
                source,
                item["title"],
                item["note"],
                item["url"],
                topic="zatca regulations",
            )
            created_or_updated += 1

        topics = list(DEFAULT_TOPICS) + list(options.get("topics") or [])
        wiki_source, _ = AIKnowledgeSource.objects.update_or_create(
            url="https://www.wikipedia.org/",
            defaults={
                "name": "Wikipedia summaries",
                "license_note": "CC BY-SA; attribution and license terms apply.",
                "is_active": True,
                "last_checked_at": now,
                "last_error": "",
            },
        )
        for topic in topics:
            try:
                response = requests.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={"action": "query", "list": "search", "srsearch": topic, "format": "json", "srlimit": 1},
                    headers={"User-Agent": "AccountingSystemAI/1.0 knowledge updater"},
                    timeout=7,
                )
                response.raise_for_status()
                rows = response.json().get("query", {}).get("search", [])
                if not rows:
                    continue
                row = rows[0]
                title = row.get("title") or topic
                summary = _clean_text(re.sub("<[^>]+>", " ", row.get("snippet") or ""))
                page_url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                upsert_ai_knowledge_entry(wiki_source, title, summary, page_url, topic=topic)
                created_or_updated += 1
            except Exception as exc:
                wiki_source.last_error = str(exc)[:1000]
                wiki_source.last_checked_at = now
                wiki_source.save(update_fields=["last_error", "last_checked_at"])

        self.stdout.write(self.style.SUCCESS(f"AI knowledge updated: {created_or_updated} entries processed."))
