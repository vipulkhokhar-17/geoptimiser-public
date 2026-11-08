"""Stage 01 artifacts -> Stage 02 extraction -> Stage 03 audit, offline and deterministic."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from geoptimiser.crawler import ArtifactWriter, LocalBodyStore, read_fetches
from geoptimiser.extraction import ExtractionWriter, extract_all
from geoptimiser.features import FeatureConfig, load_inputs
from geoptimiser.features.__main__ import main
from geoptimiser.features.audit import run_audit, write_artifacts
from geoptimiser.features.inputs import AuditInputs
from geoptimiser.schemas import FeatureResult, FetchRecord, Finding

NOW = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
ORIGIN = "https://acme.test"
ARTICLE_LD = (
    '{"@context":"https://schema.org","@type":"Article","headline":"How we price",'
    '"author":{"@type":"Person","name":"Ada"},"datePublished":"2026-01-02",'
    '"dateModified":"2026-02-03","publisher":{"@type":"Organization","name":"Acme"}}'
)
PAGES: dict[str, str] = {
    "/": (
        '<html lang="en"><head><title>Acme pricing and plans</title>'
        '<meta name="description" content="Pricing and plans for Acme teams.">'
        '<link rel="canonical" href="https://acme.test/"></head><body>'
        "<h1>Acme pricing and plans</h1><p>"
        + "Plans for every team size. "
        * 12
        + "</p>"
        '<a href="/pricing">Pricing</a> <a href="/blog/how-we-price">Blog</a> '
        '<a href="/missing">Missing</a>'
        '<script type="application/ld+json">{"@type":"Organization","name":"Acme"}</script>'
        "</body></html>"
    ),
    "/pricing": (
        '<html lang="en"><head><title>Acme pricing and plans</title>'
        '<link rel="canonical" href="https://acme.test/pricing"></head><body>'
        '<img src="/img/IMG_0001.png"><h1>Plans</h1><h3>Skipped level</h3><p>'
        + "Choose a plan that fits. "
        * 12
        + "</p>"
        '<a href="/">Home</a></body></html>'
    ),
    "/blog/how-we-price": (
        '<html lang="en"><head><title>How we price our product</title>'
        '<meta name="description" content="A look at how Acme prices.">'
        '<link rel="canonical" href="https://acme.test/blog/how-we-price"></head><body>'
        "<h1>How we price</h1><p>" + "We explain each price. " * 14 + "</p>"
        '<a href="https://nih.gov/study">Study</a> <a href="/">Home</a>'
        f'<script type="application/ld+json">{ARTICLE_LD}</script></body></html>'
    ),
}
ROBOTS = (
    "User-agent: GPTBot\nDisallow: /pricing\nSitemap: https://acme.test/sitemap.xml\n"
)


def _fetch(
    store: LocalBodyStore, path: str, body: bytes | None, **extra: Any
) -> FetchRecord:
    fields: dict[str, Any] = {
        "audit_id": "aud_e2e",
        "fetch_id": "f" + str(abs(hash(path)) % 10**8).zfill(8),
        "requested_url": ORIGIN + path,
        "outcome": "success",
        "status_code": 200,
        "final_url": ORIGIN + path,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "started_at": NOW,
        "completed_at": NOW,
    }
    if body is not None:
        fields["body"] = store.put(body).model_dump()
    return FetchRecord.model_validate(fields | extra)


@pytest.fixture
def crawl_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "crawl"
    store = LocalBodyStore(directory / "bodies")
    fetches = [_fetch(store, p, html.encode()) for p, html in PAGES.items()]
    fetches.append(
        _fetch(
            store,
            "/missing",
            None,
            outcome="http_error",
            status_code=404,
            body_not_stored_reason="non_success_status",
        )
    )
    fetches.insert(
        0,
        _fetch(
            store,
            "/robots.txt",
            ROBOTS.encode(),
            headers={"Content-Type": "text/plain"},
        ),
    )
    with ArtifactWriter(directory) as sink:
        for record in fetches:
            sink.write_fetch(record)
    with ExtractionWriter(directory / "extraction") as sink:
        extract_all(read_fetches(directory / "fetches.jsonl"), store, sink=sink)
    return directory


def test_the_audit_runs_on_real_stage_02_output(crawl_dir: Path) -> None:
    inputs = load_inputs(crawl_dir)
    assert inputs.audit_id == "aud_e2e" and inputs.site_domain == "acme.test"
    assert len(inputs.pages) == 4 and len(inputs.robots) == 1
    assert inputs.robots[0].text == ROBOTS

    run = run_audit(inputs)
    by = {(r.feature_id, r.subject_url): r for r in run.results}

    assert by["F021", ORIGIN + "/"].status == "pass"
    assert (
        by["F021", ORIGIN + "/missing"].status == "not_measured"
    )  # a 404 has no document
    assert (
        by["F022", ORIGIN + "/"].status == "fail"
        and by["F022", ORIGIN + "/pricing"].status == "fail"
    )
    assert by["F022", ORIGIN + "/blog/how-we-price"].status == "pass"
    assert by["F035", ORIGIN + "/pricing"].status == "fail"  # h1 followed by h3
    assert by["F017", ORIGIN + "/"].status == "fail"  # links to the crawled 404 page
    assert by["F004", ORIGIN + "/pricing"].status == "warning"  # GPTBot disallowed
    assert by["F004", ORIGIN + "/"].status == "pass"
    assert by["F061", ORIGIN + "/blog/how-we-price"].status == "pass"
    assert by["F069", ORIGIN + "/blog/how-we-price"].status == "pass"
    assert by["F046", ORIGIN + "/blog/how-we-price"].status == "pass"
    assert (
        by["F066", None].status == "not_applicable"
    )  # one page declares an Organization
    assert by["F007", None].status == "pass"
    assert by["F010", ORIGIN + "/blog/how-we-price"].observed_value == 1
    assert by["F009", ORIGIN + "/"].status == "not_applicable"  # entry page
    assert by["F111", None].status == "not_measured"
    # Checks unlocked by extractor v2 run on the same documents.
    assert by["F081", ORIGIN + "/pricing"].status == "fail"  # <img> without alt
    assert by["F082", ORIGIN + "/pricing"].status == "fail"  # IMG_0001.png
    assert by["F029", ORIGIN + "/"].status == "fail"  # no viewport meta in these pages
    assert by["F058", ORIGIN + "/"].status == "pass"
    assert by["F002", ORIGIN + "/"].status == "pass"
    assert by["F077", ORIGIN + "/"].observed_value["content"] == 3


def test_findings_cite_real_pages_from_the_audit(crawl_dir: Path) -> None:
    run = run_audit(load_inputs(crawl_dir))
    ids = {f.finding_id for f in run.findings}
    assert {"fnd_F022", "fnd_F017", "fnd_F004", "fnd_F035"} <= ids
    known = {p.url for p in load_inputs(crawl_dir).pages} | {ORIGIN + "/robots.txt"}
    for finding in run.findings:
        for evidence_id in finding.evidence_ids:
            assert run.evidence[evidence_id].source_url in known
    duplicate_titles = next(f for f in run.findings if f.finding_id == "fnd_F022")
    assert {run.evidence[i].source_url for i in duplicate_titles.evidence_ids} == {
        ORIGIN + "/",
        ORIGIN + "/pricing",
    }


def test_scores_expose_coverage_and_hold_back_ai_visibility(crawl_dir: Path) -> None:
    scores = run_audit(load_inputs(crawl_dir)).scores
    assert scores.overall.score is not None
    assert (
        scores.overall.feature_coverage is not None
        and scores.overall.feature_coverage < 1
    )
    pillars = {p.key: p for p in scores.pillars}
    assert pillars["ai_visibility"].score is None
    assert pillars["technical_health"].score is not None
    categories = {c.key: c for c in scores.categories}
    assert categories["L"].measured_features == 0 and categories["L"].score is None
    assert (
        categories["I"].measured_features == 2
    )  # image alt and dimensions, on one page
    assert (
        categories["I"].reportable is False
    )  # 2 of 6 scored features: below the floor


def test_artifacts_are_written_and_round_trip(crawl_dir: Path, tmp_path: Path) -> None:
    run = run_audit(load_inputs(crawl_dir))
    out = tmp_path / "features"
    write_artifacts(run, out)

    lines = (out / "feature_results.jsonl").read_text().splitlines()
    assert [FeatureResult.model_validate_json(x) for x in lines] == list(run.results)
    findings = [
        Finding.model_validate_json(x)
        for x in (out / "findings.jsonl").read_text().splitlines()
    ]
    assert findings == list(run.findings)
    evidence = [
        json.loads(x) for x in (out / "evidence.jsonl").read_text().splitlines()
    ]
    assert {e["evidence_id"] for e in evidence} == set(run.evidence)
    summary = json.loads((out / "features.json").read_text())
    assert summary["catalog_version"] == 3 and summary["audit_id"] == "aud_e2e"
    assert summary["results_by_status"]["not_measured"] > 0
    assert summary["scores"]["overall"]["feature_coverage"] < 1
    with pytest.raises(FileExistsError):
        write_artifacts(run, out)  # never overwrites an existing audit


def test_cli_runs_on_a_crawl_directory(
    crawl_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--crawl-dir", str(crawl_dir)]) == 0
    assert (crawl_dir / "features" / "features.json").exists()
    out = capsys.readouterr().out
    assert "findings" in out and "reportable" in out


def test_cli_requires_a_crawl_dir() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_thresholds_come_from_configuration(crawl_dir: Path) -> None:
    inputs = load_inputs(crawl_dir)
    strict = run_audit(inputs, FeatureConfig(max_click_depth=0))
    depths = [
        r for r in strict.results if r.feature_id == "F010" and r.status == "fail"
    ]
    assert depths and all(r.expected_value == "<= 0" for r in depths)


def test_inputs_can_be_built_without_artifacts() -> None:
    assert AuditInputs.build("aud_x", []).pages == ()
