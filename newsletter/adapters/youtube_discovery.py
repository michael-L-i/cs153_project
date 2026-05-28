"""
YouTube Data API v3 video discovery.

Given a subject, searches YouTube across several angles (interviews, podcasts,
talks, documentaries, news), enriches results with real video metadata
(duration, views, channel, publish date), ranks them, and returns the strongest
videos as DiscoveredSource objects for the YouTube transcript adapter.

Falls back to an empty list (Exa still runs) when YOUTUBE_API_KEY is not set.
"""

from __future__ import annotations

import logging
import math
import re

import httpx

from newsletter.adapters.base import DiscoveredSource
from newsletter.config import get_settings
from newsletter.enums import SourcePlatform, TrustTier
from newsletter.models import Subject

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

# Query angles, treated equally. Both first-person (interview/podcast/talk) and
# about-them (documentary/news) content is valuable for transcripts.
SEARCH_ANGLES = [
    "{name} interview",
    "{name} podcast",
    "{name} keynote talk presentation",
    "{name} fireside chat",
    "{name} documentary",
    "{name} news",
]

# Drop Shorts/clips with little sustained speech.
MIN_DURATION_SECONDS = 120

_ISO8601_DURATION = re.compile(
    r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
)


def _parse_duration(iso: str) -> int:
    """Parse an ISO-8601 duration (e.g. 'PT1H2M3S') into seconds."""
    match = _ISO8601_DURATION.fullmatch(iso or "")
    if not match:
        return 0
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _trust_tier_for(channel_title: str, subject_name: str) -> str:
    """A founder's own channel is a primary source; everything else is secondary."""
    if subject_name and subject_name.lower() in (channel_title or "").lower():
        return TrustTier.primary.value
    return TrustTier.secondary.value


def _search_video_ids(
    client: httpx.Client, query: str, api_key: str, max_results: int
) -> list[str]:
    resp = client.get(
        _SEARCH_URL,
        params={
            "key": api_key,
            "q": query,
            "part": "snippet",
            "type": "video",
            "order": "relevance",
            "relevanceLanguage": "en",
            "maxResults": max_results,
        },
        timeout=20,
    )
    resp.raise_for_status()
    ids = []
    for item in resp.json().get("items", []):
        vid = item.get("id", {}).get("videoId")
        if vid:
            ids.append(vid)
    return ids


def _fetch_video_details(
    client: httpx.Client, video_ids: list[str], api_key: str
) -> dict[str, dict]:
    """Batch-enrich up to 50 video ids with snippet/contentDetails/statistics."""
    details: dict[str, dict] = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        resp = client.get(
            _VIDEOS_URL,
            params={
                "key": api_key,
                "id": ",".join(batch),
                "part": "snippet,contentDetails,statistics",
            },
            timeout=20,
        )
        resp.raise_for_status()
        for item in resp.json().get("items", []):
            details[item["id"]] = item
    return details


def discover_youtube_videos(subject: Subject, max_videos: int = 12) -> list[DiscoveredSource]:
    """
    Search YouTube for the strongest videos about a subject.
    Returns an empty list if YOUTUBE_API_KEY is not configured.
    """
    settings = get_settings()
    if not settings.youtube_api_key:
        logger.debug("YOUTUBE_API_KEY not set — skipping YouTube discovery")
        return []

    api_key = settings.youtube_api_key
    company = subject.company_name or ""

    angles = list(SEARCH_ANGLES)
    if company:
        angles.append("{name} " + company + " interview")

    # angle that first surfaced each id, plus its rank within that angle
    first_seen: dict[str, tuple[str, int]] = {}

    with httpx.Client() as client:
        for template in angles:
            query = template.format(name=subject.name).strip()
            try:
                ids = _search_video_ids(client, query, api_key, max_results=10)
            except Exception:
                logger.exception("YouTube search failed for query: %s", query)
                continue
            for rank, vid in enumerate(ids):
                if vid not in first_seen:
                    first_seen[vid] = (query, rank)

        if not first_seen:
            logger.info("YouTube discovered 0 videos for subject '%s'", subject.name)
            return []

        try:
            details = _fetch_video_details(client, list(first_seen), api_key)
        except Exception:
            logger.exception("YouTube videos.list failed for subject '%s'", subject.name)
            return []

    scored: list[tuple[float, DiscoveredSource]] = []
    for vid, item in details.items():
        snippet = item.get("snippet", {})
        content = item.get("contentDetails", {})
        stats = item.get("statistics", {})

        duration = _parse_duration(content.get("duration", ""))
        if duration < MIN_DURATION_SECONDS:
            continue

        view_count = int(stats.get("viewCount", 0) or 0)
        query, rank = first_seen[vid]

        # composite score: relevance position (earlier = better) + popularity + length bonus
        score = (
            (10 - rank)
            + math.log10(view_count + 1)
            + min(duration / 3600, 2.0)
        )

        channel_title = snippet.get("channelTitle", "")
        scored.append(
            (
                score,
                DiscoveredSource(
                    platform=SourcePlatform.youtube.value,
                    source_type="youtube_transcript",
                    url=f"https://www.youtube.com/watch?v={vid}",
                    trust_tier=_trust_tier_for(channel_title, subject.name),
                    title=snippet.get("title"),
                    author=channel_title or None,
                    metadata_json={
                        "video_id": vid,
                        "duration_seconds": duration,
                        "view_count": view_count,
                        "published_at": snippet.get("publishedAt"),
                        "video_angle": query,
                        "via": "youtube_api",
                    },
                ),
            )
        )

    scored.sort(key=lambda s: s[0], reverse=True)
    discovered = [src for _, src in scored[:max_videos]]

    logger.info(
        "YouTube discovered %d videos for subject '%s'", len(discovered), subject.name
    )
    return discovered
