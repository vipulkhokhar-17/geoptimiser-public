from pathlib import Path

import pytest

from geoptimiser.benchmark import load_judgment_set, load_query_set
from tests.retrieval.conftest import chunks_from_pages

HERE = Path(__file__).parent


@pytest.fixture(scope="session")
def probe_chunks():
    return chunks_from_pages(HERE / "corpus.json")


@pytest.fixture(scope="session")
def paraphrase():
    return (
        load_query_set(HERE / "paraphrase_queries.json"),
        load_judgment_set(HERE / "paraphrase_judgments.json"),
    )


@pytest.fixture(scope="session")
def control():
    return (
        load_query_set(HERE / "control_queries.json"),
        load_judgment_set(HERE / "control_judgments.json"),
    )
