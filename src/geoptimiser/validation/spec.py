"""Fixture specification: a mock site and the expectations fixed before running it."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Status = Literal["pass", "fail", "warning", "not_applicable", "not_measured", "error"]
SPEC_VERSION = 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Route(_Model):
    """One URL path of the mock site.

    The body is ``text`` (inline) or the contents of ``file`` (relative to the fixture
    directory). ``{{COMMENT:N}}`` expands to an HTML comment of N bytes and
    ``{{WORDS:N}}`` to about N bytes of paragraph text. ``behavior`` simulates a
    server that drops the connection or never answers.
    """

    status: int = 200
    headers: dict[str, str] = Field(default_factory=dict)
    content_type: str | None = "text/html; charset=utf-8"
    text: str | None = None
    file: str | None = None
    behavior: Literal["normal", "drop", "hang"] = "normal"


class CrawlSettings(_Model):
    max_pages: int = 25
    max_depth: int = 2
    max_response_bytes: int = 2_000_000
    request_timeout_seconds: float = 2.0
    respect_robots: bool = True


class FeatureExpectation(_Model):
    status: Status
    # Case-insensitive fragments that must appear in the result's explanation.
    explanation_contains: tuple[str, ...] = ()
    explanation_excludes: tuple[str, ...] = ()
    limitation_contains: tuple[str, ...] = ()
    severity: str | None = None
    note: str | None = None


class FindingExpectations(_Model):
    present: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()
    severity: dict[str, str] = Field(default_factory=dict)
    text_contains: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    text_excludes: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class ScoreExpectation(_Model):
    reportable: bool | None = None
    score: float | None = None
    score_tolerance: float = 0.0005
    feature_coverage: float | None = None


class ScoreExpectations(_Model):
    overall: ScoreExpectation | None = None
    categories: dict[str, ScoreExpectation] = Field(default_factory=dict)
    # Features that must not contribute to the aggregate (redundant/non-discriminating).
    not_contributing: tuple[str, ...] = ()
    contributing: tuple[str, ...] = ()


class Expectations(_Model):
    # path -> feature id -> expectation, for page-scope features.
    pages: dict[str, dict[str, FeatureExpectation]] = Field(default_factory=dict)
    # feature id -> expectation for site-scope features (any unit may match).
    site: dict[str, FeatureExpectation] = Field(default_factory=dict)
    findings: FindingExpectations = FindingExpectations()
    scores: ScoreExpectations = ScoreExpectations()
    # Fragments that no recommendation text may contain.
    recommendation_excludes: tuple[str, ...] = ()
    recommendation_includes: tuple[str, ...] = ()


class FixtureSpec(_Model):
    spec_version: int = SPEC_VERSION
    id: str
    title: str
    description: str
    # Defect identifiers from docs/validation (A1..B6) the fixture isolates or mixes.
    defects: tuple[str, ...] = ()
    kind: Literal["isolated", "combined"] = "isolated"
    crawl: CrawlSettings = CrawlSettings()
    site: dict[str, Route]
    expect: Expectations

    # Not part of the JSON: where the fixture was loaded from.
    directory: Path | None = Field(default=None, exclude=True)

    def body_for(self, path: str) -> bytes:
        route = self.site[path]
        if route.file is not None:
            assert self.directory is not None
            raw = (self.directory / route.file).read_text(encoding="utf-8")
        else:
            raw = route.text or ""
        return _expand(raw).encode("utf-8")


def _expand(raw: str) -> str:
    import re

    def comment(match: re.Match[str]) -> str:
        size = max(int(match.group(1)), 7)
        return "<!--" + "x" * (size - 7) + "-->"

    def words(match: re.Match[str]) -> str:
        unit = "Distinct sentence number {n} describes a different product detail. "
        out, n = [], 0
        total = 0
        while total < int(match.group(1)):
            piece = unit.format(n=n)
            out.append(piece)
            total += len(piece)
            n += 1
        return "".join(out)

    raw = re.sub(r"\{\{COMMENT:(\d+)\}\}", comment, raw)
    return re.sub(r"\{\{WORDS:(\d+)\}\}", words, raw)


def load_fixture(directory: Path) -> FixtureSpec:
    data: dict[str, Any] = json.loads((directory / "spec.json").read_text("utf-8"))
    spec = FixtureSpec.model_validate(data)
    return spec.model_copy(update={"directory": directory})


def load_fixtures(root: Path) -> list[FixtureSpec]:
    """Every ``<root>/<name>/spec.json``, sorted by directory name."""
    return [
        load_fixture(p.parent) for p in sorted(root.glob("*/spec.json")) if p.is_file()
    ]
