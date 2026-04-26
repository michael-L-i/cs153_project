from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from newsletter.adapters.base import AdapterUnavailable, DiscoveredSource, FetchedArtifact, NormalizedDocument
from newsletter.config import get_settings
from newsletter.enums import DocumentKind, SourcePlatform, TrustTier
from newsletter.models import Source, Subject


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:
        return parsed.path.strip("/") or None
    if parsed.hostname and "youtube.com" in parsed.hostname:
        return parse_qs(parsed.query).get("v", [None])[0]
    return None


class YouTubeAdapter:
    platform = SourcePlatform.youtube.value

    def discover(self, subject: Subject) -> list[DiscoveredSource]:
        discovered: list[DiscoveredSource] = []
        for url in subject.youtube_urls:
            discovered.append(
                DiscoveredSource(
                    platform=self.platform,
                    source_type="youtube_video",
                    url=url,
                    trust_tier=TrustTier.primary.value,
                    metadata_json={"video_id": _extract_video_id(url), "seeded": True},
                )
            )
        return discovered

    def fetch_source(self, source: Source) -> FetchedArtifact:
        settings = get_settings()
        if settings.youtube_api_key:
            response = httpx.get(source.url, follow_redirects=True, timeout=20.0)
        else:
            response = httpx.get(source.url, follow_redirects=True, timeout=20.0)
        response.raise_for_status()
        return FetchedArtifact(
            artifact_type="youtube_watch_html",
            media_type="text/html",
            payload=response.content,
            metadata_json={"video_id": source.metadata_json.get("video_id")},
        )

    def normalize(self, source: Source, artifact: FetchedArtifact) -> NormalizedDocument:
        soup = BeautifulSoup(artifact.payload.decode("utf-8", errors="ignore"), "html.parser")
        title = source.title or (
            soup.title.string.replace("- YouTube", "").strip() if soup.title and soup.title.string else source.url
        )
        description = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            description = meta["content"].strip()

        if not description:
            raise AdapterUnavailable("YouTube page fetched but no extractable transcript or description was found.")

        content_markdown = f"# {title}\n\n{description}"
        return NormalizedDocument(
            kind=DocumentKind.transcript.value,
            title=title,
            content_markdown=content_markdown,
            content_text=description,
            metadata_json={"video_id": source.metadata_json.get("video_id")},
        )

