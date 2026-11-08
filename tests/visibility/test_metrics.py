import json

import pytest

from geoptimiser.schemas import Citation, VisibilityObservation
from geoptimiser.visibility.annotate import BrandSpec, Entity
from geoptimiser.visibility.metrics import (
    compute_metrics,
    rate,
    wilson_interval,
    write_metrics,
)

SPEC = BrandSpec(
    brand=Entity(name="Acme", domains=("acme.com",)),
    competitors=(Entity(name="Globex"), Entity(name="Initech")),
)


def make(i, text="", status="success", origin="live", cites=(), repeat=0, q=None):
    failed = status != "success"
    return VisibilityObservation(
        audit_id="a1",
        query_id=q or f"q{i}",
        query_set_version=1,
        provider="prov",
        model="m1",
        query="what",
        response_text="" if failed else text,
        citations=tuple(Citation(url=u) for u in cites),
        collection_status=status,
        error_message="failed" if failed else None,
        origin=origin,
        repeat_index=repeat,
    )


def test_wilson_hand_computed():
    lo, hi = wilson_interval(4, 10)
    assert (round(lo, 5), round(hi, 5)) == (0.16818, 0.68733)
    lo, hi = wilson_interval(0, 5)
    assert (round(lo, 5), round(hi, 5)) == (0.0, 0.43449)
    lo, hi = wilson_interval(5, 5)
    assert (round(lo, 5), round(hi, 5)) == (0.56551, 1.0)


def test_wilson_rejects_bad_input():
    for args in [(1, 0), (-1, 3), (4, 3)]:
        with pytest.raises(ValueError):
            wilson_interval(*args)


def test_zero_denominator_is_not_measured_not_zero():
    r = rate(0, 0, "nothing")
    assert r.status == "not_measured"
    assert r.rate is None and r.ci_low is None
    assert r.reason == "nothing"


def live_set():
    obs = [
        make(
            i,
            "Acme is great" if i < 4 else "other",
            cites=["https://acme.com/p"] if i < 2 else (),
        )
        for i in range(10)
    ]
    obs[0] = make(
        0, "Acme and Globex", cites=["https://acme.com/p#x", "https://docs.acme.com/q"]
    )
    return obs


def test_live_group_rates_hand_computed():
    m = compute_metrics(live_set(), SPEC, "a1")
    (g,) = m.groups
    assert (g.attempted, g.succeeded, g.errors, g.skipped) == (10, 10, 0, 0)
    assert g.real_measurement and m.has_real_measurements
    assert (g.mention_rate.numerator, g.mention_rate.denominator) == (4, 10)
    assert g.mention_rate.rate == 0.4
    assert g.mention_rate.ci_low == pytest.approx(0.16818, abs=1e-5)
    assert g.mention_rate.ci_high == pytest.approx(0.68733, abs=1e-5)
    assert g.citation_rate.numerator == 2
    assert g.cited_pages == ("https://acme.com/p", "https://docs.acme.com/q")
    assert g.competitor_mentions == {"Globex": 1, "Initech": 0}
    assert g.query_coverage.rate == 1.0
    assert g.consistency.status == "not_measured"  # no repeats
    assert m.notes == ()


def test_errors_and_skips_never_enter_denominators():
    obs = [
        make(1, "Acme"),
        make(2, status="error"),
        make(3, status="skipped"),
    ]
    (g,) = compute_metrics(obs, SPEC, "a1").groups
    assert (g.attempted, g.succeeded, g.errors, g.skipped) == (3, 1, 1, 1)
    assert g.mention_rate.denominator == 1
    assert (g.query_coverage.numerator, g.query_coverage.denominator) == (1, 3)


def test_all_failed_group_is_not_measured_with_note():
    m = compute_metrics(
        [make(1, status="error"), make(2, status="skipped")], SPEC, "a1"
    )
    (g,) = m.groups
    assert g.mention_rate.status == "not_measured"
    assert g.citation_rate.status == "not_measured"
    assert g.query_coverage.rate == 0.0 and g.query_coverage.status == "measured"
    assert not m.has_real_measurements
    assert "No successful live-provider observations" in m.notes[0]


def test_mock_and_fixture_never_real():
    obs = [
        make(1, "Acme", origin="mock"),
        make(2, "Acme", origin="fixture"),
        make(3, "Acme", origin=None),
    ]
    m = compute_metrics(obs, SPEC, "a1")
    assert {g.origin for g in m.groups} == {"mock", "fixture", "unrecorded"}
    assert not any(g.real_measurement for g in m.groups)
    assert not m.has_real_measurements
    assert any("None of it measures real" in n for n in m.notes)


def test_origins_are_not_pooled():
    m = compute_metrics(
        [make(1, "Acme", origin="live"), make(2, "x", origin="mock")], SPEC, "a1"
    )
    by = {g.origin: g for g in m.groups}
    assert by["live"].mention_rate.rate == 1.0
    assert by["mock"].mention_rate.rate == 0.0
    assert m.has_real_measurements


def test_consistency_across_repeats():
    obs = [
        make(0, "Acme", q="qa", repeat=0),
        make(0, "Acme", q="qa", repeat=1),
        make(0, "Acme", q="qb", repeat=0),
        make(0, "nope", q="qb", repeat=1),
        make(0, "Acme", q="qc"),
    ]
    (g,) = compute_metrics(obs, SPEC, "a1").groups
    assert (g.consistency.numerator, g.consistency.denominator) == (1, 2)


def test_empty_observations():
    m = compute_metrics([], SPEC, "a1")
    assert m.groups == () and not m.has_real_measurements
    assert m.notes == ("No observations were provided.",)


def test_write_metrics_roundtrip_and_no_overwrite(tmp_path):
    m = compute_metrics(live_set(), SPEC, "a1")
    path = tmp_path / "visibility_metrics.json"
    write_metrics(path, m)
    data = json.loads(path.read_text())
    assert data["schema_version"] == 1 and data["groups"][0]["origin"] == "live"
    with pytest.raises(FileExistsError):
        write_metrics(path, m)
