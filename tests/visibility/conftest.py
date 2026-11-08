from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from geoptimiser.benchmark import QuerySet, load_query_set

FIXTURES = Path(__file__).parent / "fixtures"
BENCH_FIXTURES = Path(__file__).parents[1] / "benchmark" / "fixtures"


class Clock:
    """A deterministic clock that advances one second per reading."""

    def __init__(self) -> None:
        self.now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def queries() -> QuerySet:
    """Six synthetic queries (a draft set)."""
    return load_query_set(BENCH_FIXTURES / "queryset.json")


@pytest.fixture
def reviewed(queries: QuerySet) -> QuerySet:
    return QuerySet.model_validate(
        queries.model_dump()
        | {
            "review_status": "reviewed",
            "reviewed_by": "Ada",
            "reviewed_on": "2026-01-01",
        }
    )
