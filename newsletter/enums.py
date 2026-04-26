from enum import StrEnum


class ResearchJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ResearchJobStage(StrEnum):
    queued = "queued"
    discover = "discover"
    fetch = "fetch"
    normalize = "normalize"
    extract = "extract"
    resolve = "resolve"
    assemble = "assemble"
    completed = "completed"
    failed = "failed"


class SourcePlatform(StrEnum):
    web = "web"
    youtube = "youtube"
    x = "x"


class SourceStatus(StrEnum):
    discovered = "discovered"
    fetched = "fetched"
    normalized = "normalized"
    processed = "processed"
    skipped = "skipped"
    failed = "failed"


class TrustTier(StrEnum):
    founder_owned = "founder_owned"
    primary = "primary"
    reputable_press = "reputable_press"
    secondary = "secondary"
    unknown = "unknown"


class DocumentKind(StrEnum):
    article = "article"
    transcript = "transcript"
    thread = "thread"
    post = "post"
    profile = "profile"
    other = "other"

