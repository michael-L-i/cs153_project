from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from newsletter.adapters.base import DiscoveredSource, FetchedArtifact, NormalizedDocument
from newsletter.enums import DocumentKind, SourcePlatform, TrustTier
from newsletter.models import Source, Subject


def _default_trust_tier(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    if any(part in hostname for part in ("substack.com", "founder", "company", "blog")):
        return TrustTier.primary.value
    return TrustTier.unknown.value


class WebAdapter:
    platform = SourcePlatform.web.value

    def discover(self, subject: Subject) -> list[DiscoveredSource]:
        return [
            DiscoveredSource(
                platform=self.platform,
                source_type="website",
                url=url,
                trust_tier=_default_trust_tier(url),
                metadata_json={"seeded": True},
            )
            for url in subject.canonical_urls
        ]

    def fetch_source(self, source: Source) -> FetchedArtifact:
        response = httpx.get(source.url, follow_redirects=True, timeout=20.0)
        response.raise_for_status()
        return FetchedArtifact(
            artifact_type="html",
            media_type=response.headers.get("content-type", "text/html").split(";")[0],
            payload=response.content,
            metadata_json={"final_url": str(response.url)},
        )

    def normalize(self, source: Source, artifact: FetchedArtifact) -> NormalizedDocument:
        html = artifact.payload.decode("utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = source.title or (soup.title.string.strip() if soup.title and soup.title.string else source.url)
        text_blocks = []
        for element in soup.find_all(["h1", "h2", "h3", "p", "li", "blockquote"]):
            text = " ".join(element.get_text(" ", strip=True).split())
            if text:
                text_blocks.append(text)

        content_text = "\n\n".join(text_blocks)
        if not content_text:
            content_text = unescape(re.sub(r"\s+", " ", soup.get_text(" ", strip=True))).strip()

        markdown_lines = [f"# {title}", ""]
        markdown_lines.extend(text_blocks or [content_text])
        content_markdown = "\n\n".join(line for line in markdown_lines if line)

        return NormalizedDocument(
            kind=DocumentKind.article.value,
            title=title,
            content_markdown=content_markdown,
            content_text=content_text,
            metadata_json={"normalized_from": artifact.media_type},
        )

