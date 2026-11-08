import pytest

from geoptimiser.diagnosis import diagnose
from tests.diagnosis.conftest import chunks, clock, pages, run_  # noqa: F401


@pytest.fixture(scope="session")
def diagnosis(run_, chunks):  # noqa: F811
    return diagnose(run_, chunks, clock=clock)
