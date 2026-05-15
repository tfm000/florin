"""
News summarizer — batch LLM summarisation, categorisation, and importance scoring.

Takes raw articles from the scraper and produces structured summaries using
the project's configured LLM provider (Groq by default).

Importance scoring rubric:
  9-10: Market-moving events (Fed rate decision, major earnings miss, geopolitical crisis)
  7-8:  Significant macro/sector news (CPI surprise, major M&A, regulatory action)
  5-6:  Notable company-level news (earnings beat/miss, guidance change)
  3-4:  Routine market commentary, sector trends
  1-2:  Filler, opinion pieces, listicles
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from groq import AsyncGroq

from config.settings import Settings, get_settings
from news.scraper import RawArticle

logger = logging.getLogger(__name__)

_BATCH_SIZE = 15  # articles per LLM call (keeps token usage reasonable)

CATEGORIES = [
    "Finance",
    "Politics",
    "Tech",
    "World",
    "Economy",
    "Crypto",
    "Energy",
    "Healthcare",
    "Regulatory",
    "Earnings",
    "Other",
]

_SYSTEM_PROMPT = """You are a financial news analyst. You will receive a batch of \
news article headlines and excerpts.

For each article, return a JSON array where each element has:
- "index": the article's position in the input list (0-based)
- "summary": a concise 1-2 sentence summary of the article's significance
- "category": one of {categories}
- "importance": integer 1-10 using this rubric:
    9-10: Market-moving events (Fed rate decision, major earnings miss, geopolitical crisis)
    7-8: Significant macro/sector news (CPI surprise, major M&A, regulatory action)
    5-6: Notable company-level news (earnings beat/miss, guidance change)
    3-4: Routine market commentary, sector trends
    1-2: Filler, opinion pieces, listicles
- "tickers": list of stock tickers mentioned (empty list if none)

Return ONLY a JSON array. No markdown, no explanation.""".format(categories=", ".join(CATEGORIES))


@dataclass
class SummarizedArticle:
    """A news article enriched with LLM-generated metadata."""

    headline: str
    excerpt: str = ""
    url: str = ""
    pub_date: str = ""
    source: str = ""
    summary: str = ""
    category: str = "Other"
    importance: int = 3
    tickers: list[str] = field(default_factory=list)


async def summarize_articles(
    articles: list[RawArticle],
    settings: Settings | None = None,
) -> list[SummarizedArticle]:
    """
    Summarize, categorize, and score a list of scraped articles.

    Deduplicates by headline similarity, batches articles for the LLM,
    and returns structured results sorted by importance (descending).
    """
    if not articles:
        return []

    settings = settings or get_settings()

    # Deduplicate by headline similarity
    unique = _deduplicate(articles, threshold=0.7)
    logger.info("Deduplicated %d -> %d articles", len(articles), len(unique))

    # Batch-summarize via LLM
    all_summaries: list[SummarizedArticle] = []
    for batch_start in range(0, len(unique), _BATCH_SIZE):
        batch = unique[batch_start : batch_start + _BATCH_SIZE]
        try:
            summaries = await _summarize_batch(batch, settings)
            all_summaries.extend(summaries)
        except Exception:
            logger.exception("Failed to summarize batch starting at %d", batch_start)
            # Fall back to unsummarized articles
            all_summaries.extend(_fallback_summaries(batch))

    # Sort by importance descending, then by date
    all_summaries.sort(key=lambda a: (-a.importance, a.pub_date), reverse=False)
    return all_summaries


def _deduplicate(
    articles: list[RawArticle],
    threshold: float = 0.7,
) -> list[RawArticle]:
    """Remove near-duplicate articles by headline similarity."""
    unique: list[RawArticle] = []
    seen_headlines: list[str] = []

    for article in articles:
        normalized = article.headline.lower().strip()
        is_dup = False
        for seen in seen_headlines:
            if SequenceMatcher(None, normalized, seen).ratio() >= threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(article)
            seen_headlines.append(normalized)

    return unique


async def _summarize_batch(
    articles: list[RawArticle],
    settings: Settings,
) -> list[SummarizedArticle]:
    """Send a batch of articles to the LLM for summarization."""
    # Build user prompt with numbered articles
    lines = []
    for i, article in enumerate(articles):
        date_str = article.pub_date.isoformat() if article.pub_date else "unknown"
        lines.append(
            f"[{i}] {article.headline}\n"
            f"    Source: {article.source} | Date: {date_str}\n"
            f"    Excerpt: {article.excerpt[:300] if article.excerpt else 'N/A'}"
        )
    user_prompt = "\n\n".join(lines)

    # Use Groq as default; fall back to configured provider's key
    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        response = await client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "[]"
        parsed = _parse_batch_response(raw)
    finally:
        await client.close()

    # Merge LLM output back with original article data
    results: list[SummarizedArticle] = []
    llm_by_index = {item["index"]: item for item in parsed}

    for i, article in enumerate(articles):
        llm_data = llm_by_index.get(i, {})
        category = llm_data.get("category", "Other")
        if category not in CATEGORIES:
            category = "Other"

        importance = llm_data.get("importance", 3)
        importance = max(1, min(10, int(importance)))

        results.append(
            SummarizedArticle(
                headline=article.headline,
                excerpt=article.excerpt,
                url=article.url,
                pub_date=article.pub_date.isoformat() if article.pub_date else "",
                source=article.source,
                summary=llm_data.get("summary", article.excerpt[:200]),
                category=category,
                importance=importance,
                tickers=llm_data.get("tickers", []),
            )
        )

    return results


def _parse_batch_response(raw: str) -> list[dict[str, Any]]:
    """Extract a JSON array from the LLM response."""
    cleaned = raw.strip()

    # Strip markdown code fences
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    # Try direct parse
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result
        # Groq json_object mode wraps in an object — look for an array value
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return v
        return []
    except json.JSONDecodeError:
        pass

    # Try to find a JSON array in the text
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse batch LLM response: %s", cleaned[:300])
    return []


def _fallback_summaries(articles: list[RawArticle]) -> list[SummarizedArticle]:
    """Create unsummarized placeholders when the LLM call fails."""
    return [
        SummarizedArticle(
            headline=a.headline,
            excerpt=a.excerpt,
            url=a.url,
            pub_date=a.pub_date.isoformat() if a.pub_date else "",
            source=a.source,
            summary=a.excerpt[:200] if a.excerpt else a.headline,
            category="Other",
            importance=3,
        )
        for a in articles
    ]
