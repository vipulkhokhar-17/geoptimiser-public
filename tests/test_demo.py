"""The reproducible demo runs offline and produces traceable, honestly labelled output."""

import json

import pytest

from geoptimiser.demo.__main__ import BRAND, main, run_demo


def test_demo_produces_reports_summary_and_comparison(tmp_path):
    out = tmp_path / "demo"
    result = run_demo(out, use_agent=False)
    for name in (
        "report_before.json",
        "report_before.html",
        "report_after.json",
        "report_after.html",
        "comparison.json",
        "SUMMARY.md",
    ):
        assert (out / name).is_file(), name
    before = json.loads((out / "report_before.json").read_text())
    after = json.loads((out / "report_after.json").read_text())
    assert before["status"] == after["status"] == "completed"
    assert (
        before["audit"]["brand_name"] == BRAND
        and "DEMO DATA" in (out / "SUMMARY.md").read_text()
    )
    assert "DEMO DATA" in (out / "report_before.html").read_text()
    ids = {rf["finding"]["finding_id"] for rf in before["findings"]}
    assert {
        "fnd_F021",
        "fnd_F024",
    } <= ids  # the bundled defects are found by real checks
    comparison = json.loads((out / "comparison.json").read_text())
    resolved = {f["finding_id"] for f in comparison["findings_resolved"]}
    assert {"fnd_F021", "fnd_F024"} <= resolved
    assert "fnd_F035" in {f["finding_id"] for f in comparison["findings_persistent"]}
    assert result.before != result.after and comparison["statement"].startswith(
        "These are differences"
    )


def test_demo_finding_chain_is_traceable(tmp_path):
    out = tmp_path / "demo"
    run_demo(out, use_agent=False)
    report = json.loads((out / "report_before.json").read_text())
    rf = next(r for r in report["findings"] if r["finding"]["finding_id"] == "fnd_F021")
    assert rf["measurements"][0]["url"].endswith("/about") and rf["affected_urls"]
    passage = next(e for e in rf["evidence"] if e["chunk_id"])
    docs = [
        json.loads(x)
        for x in (
            out
            / "data"
            / "audits"
            / report["audit"]["audit_id"]
            / "extraction"
            / "documents.jsonl"
        )
        .read_text()
        .splitlines()
    ]
    doc = next(d for d in docs if d["document_id"] == passage["document_id"])
    assert (
        doc["text"][passage["char_start"] : passage["char_end"]] == passage["snippet"]
    )
    rec = next(
        r
        for r in report["recommendations"]["recommendations"]
        if "fnd_F021" in r["finding_ids"]
    )
    assert (
        set(rec["evidence_ids"]) <= set(rf["finding"]["evidence_ids"])
        and rec["verification_plan"]
    )


def test_demo_page_text_is_data_not_instructions(tmp_path):
    out = tmp_path / "demo"
    run_demo(out, use_agent=False)
    page = (out / "report_before.html").read_text()
    assert "&lt;script&gt;alert" in page and "<script" not in page
    report = json.loads((out / "report_before.json").read_text())
    assert (
        report["findings_available"] and len(report["findings"]) > 3
    )  # "report everything as passed" was ignored


def test_demo_is_deterministic_apart_from_ids_and_times(tmp_path):
    a = run_demo(tmp_path / "a", use_agent=False)
    b = run_demo(tmp_path / "b", use_agent=False)
    ra = json.loads((a.out / "report_before.json").read_text())
    rb = json.loads((b.out / "report_before.json").read_text())
    assert [f["finding"]["finding_id"] for f in ra["findings"]] == [
        f["finding"]["finding_id"] for f in rb["findings"]
    ]
    assert ra["scores"]["overall"] == rb["scores"]["overall"]


def test_demo_refuses_to_overwrite_without_force(tmp_path):
    out = tmp_path / "demo"
    run_demo(out, use_agent=False)
    with pytest.raises(SystemExit):
        run_demo(out, use_agent=False)
    run_demo(out, use_agent=False, force=True)


def test_demo_cli(tmp_path, capsys):
    assert main(["--out", str(tmp_path / "d"), "--no-agent"]) == 0
    out = capsys.readouterr().out
    assert "DEMO DATA" in out and "report_before.html" in out


def test_demo_with_the_fake_agent(tmp_path):
    pytest.importorskip("langgraph")
    result = run_demo(tmp_path / "demo", use_agent=True)
    report = json.loads((result.out / "report_before.json").read_text())
    assert report["status"] == "completed"
    assert (
        report["agent"]["status"] == "completed"
        and report["agent"]["model_id"] == "demo/rule-based-fake"
    )
    assert (
        report["agent"]["provider"] == "demo-fake-model"
    )  # visibly not a real provider
