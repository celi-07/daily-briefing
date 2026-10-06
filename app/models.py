from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

Topic = Literal["finance", "crypto", "indonesia", "tech"]
TOPICS = ("finance", "crypto", "indonesia", "tech")
LABELS = {"finance": "Global Finance", "crypto": "Cryptocurrency", "indonesia": "Indonesian Market", "tech": "Technology"}


def stable_id(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:24]


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTP(S) source URLs are accepted")
    if any(c in value for c in ('\r', '\n', '\x00')):
        raise ValueError("Invalid URL characters")
    tracking = {"fbclid", "gclid", "mc_cid", "mc_eid"}
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in tracking]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urlencode(query), ""))


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Article(Record):
    id: str
    source_id: str
    source_name: str
    source_type: Literal["rss", "x", "cryptowave"]
    trust: Literal["reporter", "primary", "unknown"] = "unknown"
    url: str
    title: str
    text: str = ""
    author: str = ""
    published_at: datetime | None = None
    fetched_at: datetime
    language: str = "unknown"
    quality: Literal["full", "excerpt", "title-only"] = "excerpt"
    topics: list[Topic] = Field(default_factory=list)
    linked_urls: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    _url = field_validator("url")(canonical_url)

    @field_validator("published_at", "fetched_at")
    @classmethod
    def aware_date(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Timezone is required")
            return value.astimezone(timezone.utc)
        return value


class SourceHealth(Record):
    source_id: str
    name: str
    topics: list[Topic]
    status: Literal["ok", "partial", "failed", "disabled"]
    fetched: int = 0
    detail: str = ""


class Scores(Record):
    impact: int = Field(ge=0, le=5)
    relevance: int = Field(ge=0, le=5)
    novelty: int = Field(ge=0, le=5)
    urgency: int = Field(ge=0, le=5)

    @property
    def total(self) -> float:
        return round(20 * (self.impact * .4 + self.relevance * .25 + self.novelty * .2 + self.urgency * .15), 2)


class Fact(Record):
    text: str = Field(min_length=1, max_length=1200)
    article_ids: list[str] = Field(min_length=1)


class Assessment(Record):
    event_id: str
    # English entity + precise action + event date; never just a broad theme.
    event_key: str = Field(min_length=1, max_length=240)
    topic: Topic
    secondary_topics: list[Topic] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    scores: Scores
    evidence: Literal["supported", "limited", "disputed", "unverified"]
    primary_own_statement: bool = False
    high_risk: bool = False
    independent_origins: list[str] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    reason: str = Field(max_length=1200)


class Assessments(Record):
    items: list[Assessment]


class Event(Record):
    id: str
    article_ids: list[str]
    assessment: Assessment | None = None
    eligible: bool = False
    decision: str = "Assessment unavailable"


class Claim(Record):
    text: str = Field(min_length=1, max_length=1200)
    article_ids: list[str] = Field(min_length=1)


class Draft(Record):
    event_id: str
    headline: str = Field(min_length=1, max_length=180)
    summary: list[Claim] = Field(min_length=1, max_length=4)
    why_it_matters: str = Field(max_length=600)
    caveat: str = Field(default="", max_length=400)


class Drafts(Record):
    items: list[Draft]


class Verdict(Record):
    event_id: str
    supported: bool
    reason: str = Field(max_length=1200)


class Verdicts(Record):
    items: list[Verdict]


class Citation(Record):
    article_id: str
    source: str
    url: str
    published_at: datetime | None

    _url = field_validator("url")(canonical_url)


class Story(Record):
    event_id: str
    topic: Topic
    secondary_topics: list[Topic] = Field(default_factory=list)
    headline: str
    summary: str
    why_it_matters: str = ""
    citations: list[Citation] = Field(min_length=1)
    claims: list[Claim] = Field(default_factory=list)
    importance: float | None = None
    published_at: datetime
    status: Literal["verified-analysis", "source-excerpt", "unassessed"]
    caveat: str = ""


class MarketQuote(Record):
    ticker: str
    label: str
    price: float | None = None
    unit: str
    change_pct: float | None = None
    observed_at: datetime | None = None
    session_date: str = ""
    comparison: str = "Previous available daily close"
    stale: bool = False
    unavailable: bool = False


class CitedNote(Record):
    kind: Literal["connection", "watch"]
    text: str = Field(min_length=1, max_length=600)
    story_ids: list[str] = Field(min_length=1)


class Synthesis(Record):
    items: list[CitedNote] = Field(max_length=5)


class Digest(Record):
    edition_date: str
    window_start: datetime
    window_end: datetime
    timezone: str
    stories: list[Story] = Field(default_factory=list)
    quotes: list[MarketQuote] = Field(default_factory=list)
    health: list[SourceHealth] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    takeaways: list[str] = Field(default_factory=list)  # Story IDs; never independent AI prose.
    notes: list[CitedNote] = Field(default_factory=list)
    decisions: list[Event] = Field(default_factory=list)
    pipeline_version: str = "2.0.0"


class RenderedPart(Record):
    index: int
    total: int
    html: str
    text: str
    event_ids: list[str]
