"""
Exa-powered URL discovery.

Given a subject name, searches the web for relevant interviews, articles,
and talks, then returns them as DiscoveredSource objects to be processed
by the appropriate adapter (web or youtube).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from exa_py import Exa

from newsletter.adapters.base import DiscoveredSource
from newsletter.config import get_settings
from newsletter.enums import SourcePlatform, TrustTier
from newsletter.models import Subject

logger = logging.getLogger(__name__)

# Domains we trust for founder content
HIGH_TRUST_DOMAINS = {
    "techcrunch.com", "Forbes.com", "inc.com", "fastcompany.com",
    "theinformation.com", "wired.com", "wsj.com", "nytimes.com",
    "hbr.org", "firstround.com", "a16z.com", "ycombinator.com",
    "substack.com", "medium.com",
}

# Video discovery is owned by the YouTube Data API channel, so Exa is
# restricted to articles/press — these domains are excluded from every query.
EXCLUDE_DOMAINS = ["youtube.com", "youtu.be"]

SEARCH_QUERIES = [
    "{name} founder interview startup journey",
    "{name} CEO how we built {company}",
    "{name} entrepreneur early days company",
]


def _platform_for_url(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    if "youtube.com" in hostname or "youtu.be" in hostname:
        return SourcePlatform.youtube.value
    return SourcePlatform.web.value


def _trust_tier_for_url(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lstrip("www.")
    if any(d in hostname for d in HIGH_TRUST_DOMAINS):
        return TrustTier.reputable_press.value
    return TrustTier.secondary.value


def discover_via_exa(subject: Subject, num_results_per_query: int = 5) -> list[DiscoveredSource]:
    """
    Run Exa neural search queries for a subject and return discovered sources.
    Returns an empty list if EXA_API_KEY is not configured.
    """
    settings = get_settings()
    if not settings.exa_api_key:
        logger.debug("EXA_API_KEY not set — skipping Exa discovery")
        return []

    exa = Exa(api_key=settings.exa_api_key)
    company = subject.company_name or ""
    seen_urls: set[str] = set()
    discovered: list[DiscoveredSource] = []

    for query_template in SEARCH_QUERIES:
        query = query_template.format(name=subject.name, company=company).strip()
        try:
            results = exa.search(
                query,
                num_results=num_results_per_query,
                type="auto",
                exclude_domains=EXCLUDE_DOMAINS,
            )
            for r in results.results:
                url = r.url
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                platform = _platform_for_url(url)
                discovered.append(
                    DiscoveredSource(
                        platform=platform,
                        source_type="youtube_transcript" if platform == SourcePlatform.youtube.value else "website",
                        url=url,
                        trust_tier=_trust_tier_for_url(url),
                        title=r.title or None,
                        metadata_json={"via": "exa", "exa_score": getattr(r, "score", None)},
                    )
                )
        except Exception:
            logger.exception("Exa search failed for query: %s", query)

    logger.info("Exa discovered %d sources for subject '%s'", len(discovered), subject.name)
    return discovered
