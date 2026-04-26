from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from newsletter.models import Source, Subject


class AdapterUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class DiscoveredSource:
    platform: str
    source_type: str
    url: str
    trust_tier: str
    title: str | None = None
    author: str | None = None
    metadata_json: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class FetchedArtifact:
    artifact_type: str
    media_type: str
    payload: bytes
    metadata_json: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class NormalizedDocument:
    kind: str
    title: str
    content_markdown: str
    content_text: str
    chunk_hints: list[dict[str, object]] = field(default_factory=list)
    metadata_json: dict[str, object] = field(default_factory=dict)


class SourceAdapter(Protocol):
    platform: str

    def discover(self, subject: Subject) -> list[DiscoveredSource]:
        ...

    def fetch_source(self, source: Source) -> FetchedArtifact:
        ...

    def normalize(self, source: Source, artifact: FetchedArtifact) -> NormalizedDocument:
        ...

