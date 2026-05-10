from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled

from newsletter.adapters.base import AdapterUnavailable, DiscoveredSource, FetchedArtifact, NormalizedDocument
from newsletter.enums import DocumentKind, SourcePlatform, TrustTier
from newsletter.models import Source, Subject


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:
        return parsed.path.strip("/") or None
    if parsed.hostname and "youtube.com" in parsed.hostname:
        return parse_qs(parsed.query).get("v", [None])[0]
    return None


def _fetch_video_metadata(video_id: str) -> dict:
    """Fetch title and author from YouTube oEmbed — no API key required."""
    try:
        resp = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={video_id}", "format": "json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


def _transcript_to_text(transcript: list[dict]) -> str:
    """Join transcript segments into readable paragraphs (~60s each)."""
    lines = []
    buffer: list[str] = []
    buffer_duration = 0.0

    for segment in transcript:
        text = segment.get("text", "").strip().replace("\n", " ")
        duration = segment.get("duration", 0.0)
        if not text:
            continue
        buffer.append(text)
        buffer_duration += duration
        if buffer_duration >= 60:
            lines.append(" ".join(buffer))
            buffer = []
            buffer_duration = 0.0

    if buffer:
        lines.append(" ".join(buffer))

    return "\n\n".join(lines)


class YouTubeAdapter:
    platform = SourcePlatform.youtube.value

    def discover(self, subject: Subject) -> list[DiscoveredSource]:
        discovered: list[DiscoveredSource] = []
        for url in subject.youtube_urls:
            video_id = _extract_video_id(url)
            meta = _fetch_video_metadata(video_id) if video_id else {}
            discovered.append(
                DiscoveredSource(
                    platform=self.platform,
                    source_type="youtube_transcript",
                    url=url,
                    trust_tier=TrustTier.primary.value,
                    title=meta.get("title"),
                    author=meta.get("author_name"),
                    metadata_json={"video_id": video_id, "seeded": True},
                )
            )
        return discovered

    def fetch_source(self, source: Source) -> FetchedArtifact:
        video_id = source.metadata_json.get("video_id") or _extract_video_id(source.url)
        if not video_id:
            raise AdapterUnavailable(f"Cannot extract video ID from URL: {source.url}")

        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
        except TranscriptsDisabled:
            raise AdapterUnavailable(f"Transcripts are disabled for video {video_id}")
        except NoTranscriptFound:
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                generated = transcript_list.find_generated_transcript(["en"])
                transcript = generated.fetch()
            except Exception:
                raise AdapterUnavailable(f"No transcript available for video {video_id}")
        except Exception as exc:
            raise AdapterUnavailable(f"Transcript fetch failed for {video_id}: {exc}")

        payload = json.dumps(transcript, ensure_ascii=False).encode()
        return FetchedArtifact(
            artifact_type="youtube_transcript",
            media_type="application/json",
            payload=payload,
            metadata_json={"video_id": video_id, "segment_count": len(transcript)},
        )

    def normalize(self, source: Source, artifact: FetchedArtifact) -> NormalizedDocument:
        transcript = json.loads(artifact.payload.decode())
        content_text = _transcript_to_text(transcript)

        if not content_text.strip():
            raise AdapterUnavailable("Transcript was empty after processing.")

        video_id = source.metadata_json.get("video_id", "")
        title = source.title or f"YouTube Video {video_id}"
        content_markdown = f"# {title}\n\n{content_text}"

        return NormalizedDocument(
            kind=DocumentKind.transcript.value,
            title=title,
            content_markdown=content_markdown,
            content_text=content_text,
            metadata_json={
                "video_id": video_id,
                "segment_count": artifact.metadata_json.get("segment_count", 0),
            },
        )
