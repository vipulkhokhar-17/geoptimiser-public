"""Versioned query datasets and relevance labels (Stage 04, ADR-0015).

A *query set* is the fixed list of questions asked of every retrieval system and AI
provider, so baseline and follow-up runs compare like with like. A *judgment set*
says which targets answer which query. Both are versioned, and a judgment set names the
query set version it was written for. Neither claims real-world quality by itself:
``review_status`` and ``origin`` record who vouched for the data.
"""

import re
from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from geoptimiser.schemas import Identifier, NonBlankStr, SchemaModel, VersionedRecord

# A deliberately small, closed taxonomy for B2B SaaS buyer questions (ADR-0015).
Intent = Literal[
    "informational",  # what is X, how does X work
    "how_to",  # how do I do Y
    "comparison",  # X vs Y, alternatives to X
    "commercial_investigation",  # best X for Z, X reviews
    "transactional",  # X pricing, buy X, X demo
    "navigational",  # a specific brand or product page
]
MAX_QUERIES = 1_000
MAX_QUERY_CHARS = 300
_SPACE = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """Case- and whitespace-insensitive form used to reject duplicate queries."""
    return _SPACE.sub(" ", text.strip().lower())


class Query(SchemaModel):
    query_id: Identifier
    text: NonBlankStr = Field(max_length=MAX_QUERY_CHARS)
    intent: Intent
    topic: NonBlankStr | None = None
    tags: tuple[NonBlankStr, ...] = ()


class QuerySet(VersionedRecord):
    """A named, versioned list of queries.

    ``review_status="reviewed"`` means a named person approved the list; anything else
    is a draft and must not be presented as a validated benchmark.
    """

    name: Identifier
    version: int = Field(ge=1)
    industry: NonBlankStr
    language: NonBlankStr = "en"
    description: NonBlankStr | None = None
    review_status: Literal["draft", "reviewed"] = "draft"
    reviewed_by: NonBlankStr | None = None
    reviewed_on: date | None = None
    queries: tuple[Query, ...] = Field(max_length=MAX_QUERIES)

    @model_validator(mode="after")
    def _check_queries(self) -> Self:
        ids = [q.query_id for q in self.queries]
        if len(set(ids)) != len(ids):
            raise ValueError("query ids must be unique")
        texts = [normalize_query(q.text) for q in self.queries]
        if len(set(texts)) != len(texts):
            raise ValueError("duplicate query text (ignoring case and whitespace)")
        if self.review_status == "reviewed" and not (
            self.reviewed_by and self.reviewed_on
        ):
            raise ValueError("a reviewed query set needs reviewed_by and reviewed_on")
        if self.review_status == "draft" and self.reviewed_by:
            raise ValueError("a draft query set cannot name a reviewer")
        return self

    def get(self, query_id: str) -> Query:
        for query in self.queries:
            if query.query_id == query_id:
                return query
        raise KeyError(query_id)


class Target(SchemaModel):
    """What a judgment points at: a page, or one section of it (by heading text)."""

    url: NonBlankStr
    heading: NonBlankStr | None = None


class RelevanceJudgment(SchemaModel):
    """One explicit label. Grade 0 means *judged not relevant*, which is different
    from *not judged*: only absence of a judgment means unknown."""

    query_id: Identifier
    target: Target
    grade: int = Field(ge=0, le=3)  # 0 none, 1 marginal, 2 relevant, 3 highly relevant
    rationale: NonBlankStr | None = None


class JudgmentSet(VersionedRecord):
    name: Identifier
    version: int = Field(ge=1)
    query_set_name: Identifier
    query_set_version: int = Field(ge=1)
    # "fixture": synthetic labels for tests; "human": labelled by the named person.
    origin: Literal["fixture", "human"]
    judged_by: NonBlankStr | None = None
    judgments: tuple[RelevanceJudgment, ...]

    @model_validator(mode="after")
    def _check_judgments(self) -> Self:
        if self.origin == "human" and not self.judged_by:
            raise ValueError("human judgments must name who judged them")
        keys = [(j.query_id, j.target.url, j.target.heading) for j in self.judgments]
        if len(set(keys)) != len(keys):
            raise ValueError("a target may be judged only once per query")
        return self

    def for_query(self, query_id: str) -> tuple[RelevanceJudgment, ...]:
        return tuple(j for j in self.judgments if j.query_id == query_id)
