"""Reuses the Stage 01 mock-site fixtures for the end-to-end extraction test."""

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.crawler.conftest import (  # noqa: F401  (imported fixtures)
    make_config,
    make_fetcher,
    site,
    store,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_html() -> Callable[[str], str]:
    def read(name: str) -> str:
        return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")

    return read
