from __future__ import annotations

from newsletter.models import Dossier, Subject
from newsletter.schemas import WriterPacket


def build_writer_packet(subject: Subject, dossier: Dossier, max_claims: int, max_quotes: int, max_events: int) -> WriterPacket:
    sections = dossier.sections
    return WriterPacket(
        subject={
            "id": subject.id,
            "name": subject.name,
            "company_name": subject.company_name,
        },
        dossier_version=dossier.version,
        founder_profile=sections.get("founder_profile", {}),
        company_snapshot=sections.get("company_snapshot", {}),
        timeline=sections.get("startup_journey_timeline", [])[:max_events],
        core_themes=sections.get("core_themes", []),
        notable_quotes=sections.get("notable_quotes", [])[:max_quotes],
        supported_claims=sections.get("supported_claims", [])[:max_claims],
        source_coverage=sections.get("source_coverage", {}),
        open_questions=sections.get("open_questions", []),
    )

