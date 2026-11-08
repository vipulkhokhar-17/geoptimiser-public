import threading

import pytest

from geoptimiser.app import AuditOptions, AuditSubmission, TargetError, normalize_target
from geoptimiser.app.jobs import JobRunner, QueueFull


@pytest.mark.parametrize(
    ("raw", "url", "key"),
    [
        ("Example.COM", "https://example.com/", "https://example.com/"),
        (
            "https://www.Example.com/Pricing/?utm=1#top",
            "https://www.example.com/Pricing/",
            "https://www.example.com/Pricing",
        ),
        (
            "http://example.com//a///b",
            "http://example.com/a/b",
            "http://example.com/a/b",
        ),
        ("https://example.com:443/", "https://example.com/", "https://example.com/"),
        ("  https://example.com  ", "https://example.com/", "https://example.com/"),
    ],
)
def test_targets_are_normalised(raw, url, key):
    target = normalize_target(raw)
    assert (target.url, target.normalized_url) == (url, key)
    assert target.domain == url.split("/")[2]


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "ftp://example.com",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://",
        "https://user:pw@example.com",
        "http://localhost",
        "http://127.0.0.1",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://intranet",
        "http://printer.local",
        "http://a.internal/",
        "https://example.com:8443/",
        "http://example.com:22/",
        "https://exa mple.com",
        "https://example.com/\nHost: evil",
        "x" * 3000,
        "http://2130706433/",
    ],
)
def test_unsafe_or_unusable_targets_are_rejected(raw):
    with pytest.raises(TargetError):
        normalize_target(raw)


def test_submission_bounds():
    for bad in ({"url": "x"}, {"url": "a.com", "authorization_confirmed": True, "extra": 1},
                {"url": "a.com", "authorization_confirmed": True, "options": {"max_pages": 1000}},
                {"url": "a.com", "authorization_confirmed": True, "options": {"retrieval": "web"}},
                {"url": "a.com", "authorization_confirmed": "yes"},
                {"url": "a.com", "authorization_confirmed": True, "brand_name": "x" * 500}):  # fmt: skip
        with pytest.raises(ValueError):
            AuditSubmission.model_validate(bad)
    ok = AuditSubmission(url="a.com", authorization_confirmed=True)
    assert ok.options == AuditOptions() and ok.options.use_agent is False


def test_runner_runs_jobs_and_bounds_the_queue():
    gate, done = threading.Event(), []
    runner = JobRunner(workers=1, max_queued=1)
    runner.submit(lambda: gate.wait(5) and done.append(1))  # occupies the worker
    import time

    time.sleep(0.2)  # let the worker take it off the queue
    runner.submit(lambda: done.append(2))  # fills the queue
    with pytest.raises(QueueFull):
        for _ in range(3):
            runner.submit(lambda: None)
    gate.set()
    assert runner.wait_idle(5) and sorted(done) == [1, 2]
    runner.shutdown()
    with pytest.raises(QueueFull):
        runner.submit(lambda: None)


def test_runner_survives_a_crashing_job():
    runner = JobRunner()
    out = []
    runner.submit(lambda: 1 / 0)
    runner.submit(lambda: out.append("ok"))
    assert runner.wait_idle(5) and out == ["ok"] and runner.alive
    runner.shutdown()
