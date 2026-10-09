import json
import os
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator

from app.models import Record, Topic, canonical_url

ROOT = Path(__file__).resolve().parent.parent


class Source(Record):
    id: str
    name: str
    kind: Literal["rss", "x", "cryptowave"]
    url: str = ""
    topics: list[Topic]
    trust: Literal["primary", "reporter", "unknown"] = "reporter"
    enabled: bool = True
    queries: list[str] = Field(default_factory=list)
    primary_accounts: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        return canonical_url(value) if value else value


class Settings(Record):
    ai_provider: Literal["openai", "gemini"] = "openai"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5.6-terra"
    openai_fallback_model: str = ""
    openai_reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "none"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_fallback_model: str = ""
    gmail_address: str = ""
    gmail_app_password: SecretStr = SecretStr("")
    recipient_email: str = ""
    x_bearer_token: SecretStr = SecretStr("")
    x_api_schema: Literal["post", "tweet"] = "post"
    timezone: str = "Asia/Jakarta"
    language: str = "English"
    window_hours: int = Field(default=24, ge=1, le=168)
    importance_threshold: float = Field(default=70, ge=0, le=100)
    http_timeout: float = Field(default=15, ge=1, le=60)
    http_requests: int = Field(default=400, ge=1)
    http_bytes: int = Field(default=3_000_000, ge=1024)
    workers: int = Field(default=6, ge=1, le=12)
    source_pages: int = Field(default=10, ge=1, le=100)
    ai_requests: int = Field(default=120, ge=1)
    ai_tokens: int = Field(default=400_000, ge=1000)
    ai_seconds: int = Field(default=1200, ge=1)
    ai_batch_size: int = Field(default=6, ge=1, le=20)
    ai_assessment_fraction: float = Field(default=.8, ge=.1, le=.9)
    assessment_evidence_chars: int = Field(default=3000, ge=1000, le=40_000)
    evidence_chars: int = Field(default=10_000, ge=1000, le=40_000)
    html_bytes: int = Field(default=80 * 1024, ge=12_000)
    enrichment: bool = True
    sources_file: Path = ROOT / "config" / "sources.json"
    output_dir: Path = Path("artifacts")
    state_dir: Path = Path(".state")

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("gmail_address", "recipient_email")
    @classmethod
    def valid_email(cls, value):
        if value and ("@" not in value or any(c in value for c in ("\r", "\n", " ", ",", ";"))):
            raise ValueError("Invalid email address")
        return value

    @classmethod
    def from_env(cls):
        # Ignore blank workflow variables so defaults remain effective.
        values = {key: os.environ[key.upper()] for key in cls.model_fields
                  if os.environ.get(key.upper(), "").strip()}
        return cls(**values)

    def sources(self) -> list[Source]:
        sources = [Source.model_validate(item) for item in json.loads(self.sources_file.read_text(encoding="utf-8"))]
        if len({s.id for s in sources}) != len(sources):
            raise ValueError("Source IDs must be unique")
        return sources

    def validate_mail(self):
        if not self.gmail_address or not self.gmail_app_password.get_secret_value():
            raise ValueError("GMAIL_ADDRESS and GMAIL_APP_PASSWORD are required to send email")

    def validate_ai(self):
        if self.ai_provider == "openai" and self.gemini_api_key.get_secret_value().strip():
            return
        key_name = "OPENAI_API_KEY" if self.ai_provider == "openai" else "GEMINI_API_KEY"
        if not getattr(self, key_name.lower()).get_secret_value().strip():
            raise ValueError(f"{key_name} is required for AI_PROVIDER={self.ai_provider}; configure the Actions secret before running")
