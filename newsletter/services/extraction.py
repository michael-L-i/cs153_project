from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

from dateutil import parser as date_parser

from newsletter.models import Claim, Document, Event, Quote, Source, Subject

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}

EVENT_HINTS = ("founded", "launched", "raised", "started", "pivot", "joined", "acquired", "built", "grew")


def split_text_into_chunks(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue
        if len(current) + 2 + len(paragraph) <= max_chars:
            current = f"{current}\n\n{paragraph}"
            continue
        chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)

    if not chunks and text.strip():
        return [text.strip()]
    return chunks


def sentence_candidates(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return [sentence.strip() for sentence in sentences if len(sentence.strip()) >= 40]


def extract_claim_payloads(subject: Subject, source: Source, document: Document) -> list[dict[str, object]]:
    claims: list[dict[str, object]] = []
    for sentence in sentence_candidates(document.content_text)[:8]:
        claims.append(
            {
                "claim_type": "narrative_fact",
                "statement": sentence,
                "confidence": 0.45,
                "citations": [{"source_id": source.id, "url": source.url, "document_id": document.id}],
                "rationale": f"Extracted from normalized {source.platform} content for {subject.name}.",
            }
        )
    return claims


def extract_event_payloads(source: Source, document: Document) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for sentence in sentence_candidates(document.content_text):
        lower_sentence = sentence.lower()
        if not any(hint in lower_sentence for hint in EVENT_HINTS):
            continue
        event_date: date | None = None
        try:
            parsed = date_parser.parse(sentence, fuzzy=True, default=datetime(2000, 1, 1))
            event_date = parsed.date()
        except (ValueError, OverflowError, TypeError):
            year_match = re.search(r"\b(19|20)\d{2}\b", sentence)
            if year_match:
                event_date = date(int(year_match.group(0)), 1, 1)

        events.append(
            {
                "event_type": "milestone",
                "summary": sentence,
                "event_date": event_date,
                "confidence": 0.5 if event_date else 0.35,
                "citations": [{"source_id": source.id, "url": source.url, "document_id": document.id}],
            }
        )
    return events[:10]


def extract_quote_payloads(source: Source, document: Document, default_speaker: str | None) -> list[dict[str, object]]:
    quotes: list[dict[str, object]] = []
    for match in re.finditer(r"[\"“](.{40,280}?)[\"”]", document.content_text):
        quote_text = match.group(1).strip()
        quotes.append(
            {
                "speaker": default_speaker,
                "quote_text": quote_text,
                "confidence": 0.4,
                "citations": [{"source_id": source.id, "url": source.url, "document_id": document.id}],
            }
        )
    return quotes[:8]


def derive_core_themes(claims: list[Claim]) -> list[str]:
    counter: Counter[str] = Counter()
    for claim in claims:
        for token in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", claim.statement.lower()):
            if token not in STOPWORDS:
                counter[token] += 1
    return [token for token, _count in counter.most_common(8)]
