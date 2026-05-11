from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from newsletter.adapters.base import DiscoveredSource, FetchedArtifact, NormalizedDocument
from newsletter.config import get_settings
from newsletter.enums import DocumentKind, SourcePlatform, TrustTier
from newsletter.models import Source, Subject

FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v1/scrape"


def _default_trust_tier(url: str) -> str:
    hostname = urlparse(url).hostname or ""
    if any(part in hostname for part in ("substack.com", "founder", "company", "blog")):
        return TrustTier.primary.value
    return TrustTier.unknown.value


def _scrape_with_firecrawl(url: str, api_key: str) -> dict | None:
    """Call Firecrawl and return parsed response dict, or None on failure."""
    try:
        resp = httpx.post(
            FIRECRAWL_SCRAPE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=30,
        )
        if resp.status_code == 200:
            body = resp.json()
            if body.get("success") and body.get("data"):
                return body["data"]
    except Exception:
        pass
    return None


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
        settings = get_settings()

        if settings.firecrawl_api_key:
            data = _scrape_with_firecrawl(source.url, settings.firecrawl_api_key)
            if data:
                markdown = data.get("markdown", "")
                meta = data.get("metadata", {})
                return FetchedArtifact(
                    artifact_type="firecrawl_markdown",
                    media_type="text/markdown",
                    payload=markdown.encode(),
                    metadata_json={
                        "title": meta.get("title", ""),
                        "final_url": meta.get("url", source.url),
                        "via": "firecrawl",
                    },
                )

        # fallback: plain httpx
        response = httpx.get(
            source.url,
            follow_redirects=True,
            timeout=20.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FounderResearchBot/1.0)"},
        )
        response.raise_for_status()
        return FetchedArtifact(
            artifact_type="html",
            media_type="text/html",
            payload=response.content,
            metadata_json={"final_url": str(response.url), "via": "httpx"},
        )

    def normalize(self, source: Source, artifact: FetchedArtifact) -> NormalizedDocument:
        if artifact.artifact_type == "firecrawl_markdown":
            content_markdown = artifact.payload.decode("utf-8", errors="ignore")
            # strip markdown syntax to produce plain text
            content_text = re.sub(r"^#{1,6}\s+", "", content_markdown, flags=re.MULTILINE)
            content_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", content_text)
            content_text = re.sub(r"[*_`~]+", "", content_text)
            content_text = re.sub(r"\n{3,}", "\n\n", content_text).strip()
            title = source.title or artifact.metadata_json.get("title") or source.url
            return NormalizedDocument(
                kind=DocumentKind.article.value,
                title=title,
                content_markdown=content_markdown,
                content_text=content_text,
                metadata_json={"via": "firecrawl", "final_url": artifact.metadata_json.get("final_url", source.url)},
            )

        # fallback: parse HTML
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
            metadata_json={"via": "httpx", "final_url": artifact.metadata_json.get("final_url", source.url)},
        )
