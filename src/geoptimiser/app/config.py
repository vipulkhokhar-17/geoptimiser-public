"""Server-side application settings. API clients cannot change any of these."""

import ipaddress
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from geoptimiser.agent import AgentConfig
from geoptimiser.schemas import SchemaModel

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "[::1]", "::1")

_HOST = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_IPV6 = re.compile(r"^[0-9a-f:]+$")


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_origin(value: str) -> str:
    """Validate a bare web origin; HTTP is allowed only for loopback hosts."""
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise ValueError(f"not a valid origin: {value!r}") from None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or "*" in value:
        raise ValueError("an origin looks like https://host[:port]")
    if not (_HOST.match(host) or _IPV6.match(host)):
        raise ValueError("an origin looks like https://host[:port]")
    if (
        parts.username
        or parts.password
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise ValueError("an origin has no credentials, path, query or fragment")
    if parts.scheme == "http" and not _is_loopback_host(host):
        raise ValueError("plain http origins are only allowed for localhost")
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}" + (f":{port}" if port else "")


class AppConfig(SchemaModel):
    data_dir: Path
    max_pages_cap: int = Field(default=50, ge=1, le=500)
    max_depth_cap: int = Field(default=3, ge=0, le=10)
    crawl_overrides: dict[str, Any] = Field(default_factory=dict)
    workers: int = Field(default=1, ge=1, le=4)
    max_queued: int = Field(default=10, ge=1, le=100)
    agent_enabled: bool = True
    max_agent_audits_per_hour: int = Field(default=20, ge=0, le=1000)
    agent: AgentConfig = AgentConfig()
    retrieval_settings_path: Path | None = None
    allowed_hosts: tuple[str, ...] = LOOPBACK_HOSTS
    cors_origins: tuple[str, ...] = ()
    log_level: str = "INFO"

    @field_validator("cors_origins")
    @classmethod
    def _check_origins(cls, origins: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(validate_origin(o) for o in origins)
        for origin in validated:
            host = urlsplit(origin).hostname or ""
            if not _is_loopback_host(host):
                raise ValueError(
                    "CORS origins must use localhost or a loopback IP; "
                    "the application is local-only"
                )
        return validated
