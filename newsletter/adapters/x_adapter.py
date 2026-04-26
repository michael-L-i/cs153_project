from __future__ import annotations

from newsletter.adapters.base import AdapterUnavailable, DiscoveredSource, FetchedArtifact, NormalizedDocument
from newsletter.config import get_settings
from newsletter.enums import SourcePlatform, TrustTier
from newsletter.models import Source, Subject


class XAdapter:
    platform = SourcePlatform.x.value

    def discover(self, subject: Subject) -> list[DiscoveredSource]:
        discovered: list[DiscoveredSource] = []
        for handle in subject.x_handles:
            clean_handle = handle.lstrip("@")
            discovered.append(
                DiscoveredSource(
                    platform=self.platform,
                    source_type="x_profile",
                    url=f"https://x.com/{clean_handle}",
                    trust_tier=TrustTier.primary.value,
                    metadata_json={"handle": clean_handle, "seeded": True},
                )
            )
        return discovered

    def fetch_source(self, source: Source) -> FetchedArtifact:
        settings = get_settings()
        if not settings.x_bearer_token:
            raise AdapterUnavailable("X API bearer token not configured.")
        raise AdapterUnavailable("X API integration is scaffolded but not yet wired to endpoint calls.")

    def normalize(self, source: Source, artifact: FetchedArtifact) -> NormalizedDocument:
        raise AdapterUnavailable("X normalization is unavailable without fetched API payloads.")
