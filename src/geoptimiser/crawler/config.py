"""Crawl limits. Operational limits live here, not in the shared schemas (ADR-0004)."""

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_USER_AGENT = "GeoptimiserBot/0.1"


class CrawlConfig(BaseModel):
    """Bounds for one audit crawl. Every limit is finite and must be positive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_pages: int = Field(default=25, ge=1, le=500)
    max_depth: int = Field(default=2, ge=0, le=10)
    max_response_bytes: int = Field(default=2_000_000, ge=1)
    max_audit_bytes: int = Field(default=50_000_000, ge=1)
    max_robots_bytes: int = Field(default=500_000, ge=1)
    # Socket-level timeout applied to connect and to every read.
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    # Wall-clock bound for one whole fetch (all redirect hops, headers and body).
    max_fetch_seconds: float = Field(default=30.0, gt=0)
    max_audit_seconds: float = Field(default=600.0, gt=0)
    max_redirects: int = Field(default=5, ge=0, le=20)
    min_request_interval_seconds: float = Field(default=1.0, ge=0)
    max_links_per_page: int = Field(default=500, ge=1)
    max_url_length: int = Field(default=2048, ge=16)
    allowed_ports: frozenset[int] = frozenset({80, 443})
    follow_query_strings: bool = False
    respect_robots: bool = True
    user_agent: str = DEFAULT_USER_AGENT
