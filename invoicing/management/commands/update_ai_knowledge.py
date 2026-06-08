import re
from urllib.parse import quote

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from invoicing.ai_services import ZATCA_OFFICIAL_REGULATIONS, upsert_ai_knowledge_entry
from invoicing.models import AIKnowledgeSource


DEFAULT_TOPICS = (
    "financial accounting", "management accounting", "cost accounting", "auditing",
    "IFRS", "cash flow", "working capital", "accounts receivable", "accounts payable",
    "inventory management", "inventory turnover", "point of sale", "cashier system",
    "electronic invoicing Saudi Arabia", "VAT Saudi Arabia", "ZATCA e-invoicing",
    "small business Saudi Arabia", "retail management", "pricing strategy",
    "gross margin", "profit margin", "break even analysis", "financial statements",
    "balance sheet", "income statement", "trial balance", "general ledger",
    "project management", "risk management", "business plan", "market research",
    "customer relationship management", "supply chain management", "procurement",
    "human resources management", "payroll", "investment analysis", "business analytics",
    "artificial intelligence", "machine learning", "data analysis", "cybersecurity",
    "cloud computing", "software as a service", "e-commerce", "digital marketing",
    "economics", "finance", "statistics", "operations management", "entrepreneurship",
    "algebra", "geometry", "calculus", "probability theory", "number theory",
    "classical mechanics", "electromagnetism", "thermodynamics", "quantum mechanics",
    "organic chemistry", "inorganic chemistry", "biochemistry", "molecular biology",
    "genetics", "ecology", "human anatomy", "medicine", "public health",
    "astronomy", "astrophysics", "cosmology", "solar system", "space exploration",
    "civil engineering", "mechanical engineering", "electrical engineering",
    "industrial engineering", "software engineering", "architecture",
    "geography", "physical geography", "human geography", "world history",
    "Saudi Arabia history", "Arab history", "Islamic civilization",
    "Arabic grammar", "Arabic literature", "English grammar", "linguistics",
    "philosophy", "psychology", "sociology", "political science",
    "constitutional law", "international law", "environmental science",
    "climate change", "renewable energy", "agriculture", "food science",
    "computer science", "algorithms", "databases", "computer networks",
    "operating systems", "web development", "mobile development", "robotics",
    "natural language processing", "computer vision", "data science",
    "Palestinian territories occupation international law",
    "Palestinian Nakba displacement 1948",
    "Israeli settlements occupied Palestinian territory",
    "Palestinian human rights United Nations",
    "International Court of Justice occupied Palestinian territory advisory opinion 2024",
    "International Criminal Court Palestine situation",
)

WIKIDATA_TOPICS = (
    "accounting", "financial statement", "cash flow", "inventory", "tax",
    "business", "project management", "artificial intelligence", "economics",
    "mathematics", "physics", "chemistry", "biology", "astronomy", "engineering",
    "geography", "history", "language", "computer science", "medicine",
)

OPENALEX_TOPICS = (
    "accounting information systems", "financial accounting", "inventory management",
    "small business performance", "Saudi Arabia VAT", "electronic invoicing",
    "cash flow forecasting", "retail analytics", "business intelligence",
    "mathematics education", "physics education", "astronomy", "engineering design",
    "Arabic natural language processing", "geographic information science",
    "renewable energy", "machine learning", "public health",
)


def _clean_text(text, limit=900):
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    return clean[:limit]


def _is_relevant_result(topic, title, description=""):
    stop_words = {
        "the", "and", "for", "with", "from", "into", "using", "analysis",
        "system", "science", "management", "education", "research",
    }
    topic_tokens = {
        token for token in re.findall(r"[a-z0-9]+", (topic or "").lower())
        if len(token) > 2 and token not in stop_words
    }
    if not topic_tokens:
        return True
    candidate = f"{title} {description}".lower()
    return any(token in candidate for token in topic_tokens)


class Command(BaseCommand):
    help = "Update the AI knowledge base from configured free and official internet sources."

    def add_arguments(self, parser):
        parser.add_argument("--topic", action="append", dest="topics", help="Extra public knowledge topic to fetch.")
        parser.add_argument("--limit", type=int, default=1, help="Maximum rows per public source/topic.")

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

        limit = max(1, min(int(options.get("limit") or 1), 5))
        topics = list(dict.fromkeys(list(DEFAULT_TOPICS) + list(options.get("topics") or [])))
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
                    params={"action": "query", "list": "search", "srsearch": topic, "format": "json", "srlimit": limit},
                    headers={"User-Agent": "AccountingSystemAI/1.0 knowledge updater"},
                    timeout=7,
                )
                response.raise_for_status()
                rows = response.json().get("query", {}).get("search", [])
                for row in rows[:limit]:
                    title = row.get("title") or topic
                    summary = _clean_text(re.sub("<[^>]+>", " ", row.get("snippet") or ""))
                    if not _is_relevant_result(topic, title, summary):
                        continue
                    page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                    upsert_ai_knowledge_entry(wiki_source, title, summary, page_url, topic=topic)
                    created_or_updated += 1
            except Exception as exc:
                wiki_source.last_error = str(exc)[:1000]
                wiki_source.last_checked_at = now
                wiki_source.save(update_fields=["last_error", "last_checked_at"])

        wikidata_source, _ = AIKnowledgeSource.objects.update_or_create(
            url="https://www.wikidata.org/",
            defaults={
                "name": "Wikidata public facts",
                "license_note": "CC0 public-domain structured data.",
                "is_active": True,
                "last_checked_at": now,
                "last_error": "",
            },
        )
        for topic in list(dict.fromkeys(list(WIKIDATA_TOPICS) + list(options.get("topics") or []))):
            try:
                response = requests.get(
                    "https://www.wikidata.org/w/api.php",
                    params={
                        "action": "wbsearchentities",
                        "search": topic,
                        "language": "en",
                        "format": "json",
                        "limit": limit,
                    },
                    headers={"User-Agent": "AccountingSystemAI/1.0 knowledge updater"},
                    timeout=7,
                )
                response.raise_for_status()
                for row in response.json().get("search", [])[:limit]:
                    title = row.get("label") or topic
                    description = row.get("description") or "Structured public knowledge entry."
                    if not _is_relevant_result(topic, title, description):
                        continue
                    entity_id = row.get("id") or ""
                    page_url = f"https://www.wikidata.org/wiki/{entity_id}" if entity_id else "https://www.wikidata.org/"
                    upsert_ai_knowledge_entry(wikidata_source, title, _clean_text(description), page_url, topic=topic)
                    created_or_updated += 1
            except Exception as exc:
                wikidata_source.last_error = str(exc)[:1000]
                wikidata_source.last_checked_at = now
                wikidata_source.save(update_fields=["last_error", "last_checked_at"])

        openalex_source, _ = AIKnowledgeSource.objects.update_or_create(
            url="https://openalex.org/",
            defaults={
                "name": "OpenAlex research index",
                "license_note": "CC0 open research metadata.",
                "is_active": True,
                "last_checked_at": now,
                "last_error": "",
            },
        )
        for topic in list(dict.fromkeys(list(OPENALEX_TOPICS) + list(options.get("topics") or []))):
            try:
                response = requests.get(
                    "https://api.openalex.org/works",
                    params={"search": topic, "per-page": limit, "sort": "cited_by_count:desc"},
                    headers={"User-Agent": "AccountingSystemAI/1.0 knowledge updater"},
                    timeout=7,
                )
                response.raise_for_status()
                for row in response.json().get("results", [])[:limit]:
                    title = row.get("title") or topic
                    if not _is_relevant_result(topic, title):
                        continue
                    year = row.get("publication_year") or "unknown year"
                    cited = row.get("cited_by_count") or 0
                    source_url = row.get("doi") or row.get("id") or "https://openalex.org/"
                    summary = f"Research metadata published in {year}; cited by {cited} works in OpenAlex."
                    upsert_ai_knowledge_entry(openalex_source, title, summary, source_url, topic=topic)
                    created_or_updated += 1
            except Exception as exc:
                openalex_source.last_error = str(exc)[:1000]
                openalex_source.last_checked_at = now
                openalex_source.save(update_fields=["last_error", "last_checked_at"])

        self.stdout.write(self.style.SUCCESS(f"AI knowledge updated: {created_or_updated} entries processed."))
