"""Security checks for the application layer (all local; no network)."""

import json
import re
from pathlib import Path

import pytest

from geoptimiser.app import TargetError, normalize_target
from geoptimiser.app.pipeline import default_fetcher_factory
from geoptimiser.crawler import CrawlConfig, LocalBodyStore

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize(
    "raw",
    [
        "http://evil.com@127.0.0.1/",
        "http://127.0.0.1#@acme.test/",
        "http://acme.test\\@127.0.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:7f00:1]/",
        "http://0x7f.0.0.1/",
        "http://0x7f000001/",
        "http://017700000001/",
        "http://127.1/",
        "http://2130706433/",
        "http://localhost./",
        "http://LOCALHOST/",
        "http://foo.localhost/",
        "http://metadata.google.internal/",
        "http://169.254.169.254/",
        "http://100.100.100.200/",
        "http://[fd00:ec2::254]/",
        "http://acme.test:0/",
        "http://acme.test:65535/",
        "http://acme.test:/x\x00",
        "gopher://acme.test/",
        "data:text/html,<script>alert(1)</script>",
        "https://ａｃｍｅ.test/",
        "https://xn--/",
    ],
)
def test_url_parsing_tricks_are_rejected(raw):
    with pytest.raises(TargetError):
        normalize_target(raw)


def test_accepted_targets_never_carry_a_query_fragment_or_credentials():
    target = normalize_target("https://Acme.Test/path/?token=abc&x=1#secret")
    assert "token" not in target.url and "secret" not in target.url
    assert "?" not in target.normalized_url and "#" not in target.normalized_url


def test_the_default_fetcher_still_enforces_the_public_ip_policy(tmp_path):
    fetcher = default_fetcher_factory(
        CrawlConfig(), LocalBodyStore(tmp_path), "aud_x", lambda h: True
    )
    for url in (
        "http://127.0.0.1/",
        "http://10.1.2.3/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[fd00:ec2::254]/",
    ):
        record = fetcher.fetch(url).record
        assert (
            record.outcome == "transport_error"
            and record.error_type == "blocked_address"
        ), url
    assert fetcher.config.respect_robots and fetcher.config.allowed_ports == frozenset(
        {80, 443}
    )


def test_users_cannot_loosen_crawl_policy_through_options():
    from geoptimiser.app import AuditOptions

    fields = set(AuditOptions.model_fields)
    assert fields == {"max_pages", "max_depth", "retrieval", "use_agent"}
    with pytest.raises(ValueError):
        AuditOptions.model_validate({"respect_robots": False})
    with pytest.raises(ValueError):
        AuditOptions.model_validate({"allowed_ports": [22]})


def test_app_cors_origins_are_loopback_only(tmp_path):
    from geoptimiser.app.config import AppConfig

    local = AppConfig(
        data_dir=tmp_path / "local", cors_origins=("http://127.0.0.1:8080",)
    )
    assert local.cors_origins == ("http://127.0.0.1:8080",)
    with pytest.raises(ValueError, match="loopback"):
        AppConfig(
            data_dir=tmp_path / "remote", cors_origins=("https://geoptimiser.me",)
        )


def test_the_source_tree_contains_no_credentials():
    pattern = re.compile(
        r"sk-or-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9]{32,}|Bearer\s+[A-Za-z0-9._-]{20,}|AKIA[0-9A-Z]{16}"
    )
    offenders = []
    for base in ("src", "docs", "configs", "README.md", ".env.example", ".github"):
        path = ROOT / base
        files = (
            [path]
            if path.is_file()
            else [
                p
                for p in path.rglob("*")
                if p.is_file()
                and p.suffix
                in {".py", ".md", ".json", ".yml", ".js", ".html", ".example", ""}
            ]
        )
        for file in files:
            if pattern.search(file.read_text(errors="ignore")):
                offenders.append(str(file.relative_to(ROOT)))
    assert offenders == []
    example = (ROOT / ".env.example").read_text()
    assert "OPENROUTER_API_KEY=" in example and not re.search(
        r"OPENROUTER_API_KEY=\S", example.replace("# OPENROUTER_API_KEY=", "")
    )


def test_data_directory_is_git_ignored():
    ignore = (ROOT / ".gitignore").read_text()
    assert "data/" in ignore and "*.db" in ignore and ".env" in ignore


def test_the_api_module_defines_no_fetch_or_file_routes():
    source = (ROOT / "src/geoptimiser/app/api.py").read_text()
    routes = re.findall(r'@app\.(?:get|post|put|delete|patch)\("([^"]+)"', source)
    assert all(r.startswith("/api/v1/") for r in routes)
    assert not any(
        word in r
        for r in routes
        for word in ("fetch", "proxy", "file", "path", "exec", "run")
    )
    assert "StaticFiles" not in source and "FileResponse" not in source


def test_downloaded_report_keeps_a_script_free_policy(tmp_path):
    from geoptimiser.app.report import _META_CSP

    assert "default-src 'none'" in _META_CSP and "script-src" not in _META_CSP


def test_comparison_files_are_replaced_atomically(tmp_path):
    import threading

    from geoptimiser.app.service import write_json_atomic_overwrite

    target = tmp_path / "cmp" / "c.json"
    write_json_atomic_overwrite(target, {"v": 0})
    errors: list[BaseException] = []

    def writer(n: int) -> None:
        try:
            for i in range(50):
                write_json_atomic_overwrite(target, {"v": n * 100 + i})
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert "v" in json.loads(target.read_text())
    assert [p.name for p in target.parent.iterdir()] == ["c.json"]
