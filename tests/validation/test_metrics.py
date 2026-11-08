import pytest

from geoptimiser.validation import BinaryCounts, wilson_interval


def test_precision_and_recall_follow_the_stated_formulas() -> None:
    c = BinaryCounts(tp=8, fp=2, tn=5, fn=2)
    assert c.precision == pytest.approx(8 / 10)
    assert c.recall == pytest.approx(8 / 10)
    assert c.n == 17


def test_zero_denominators_are_undefined_not_zero_or_one() -> None:
    assert BinaryCounts(tn=5).precision is None  # nothing predicted positive
    assert BinaryCounts(tn=5).recall is None  # no true positives to find
    assert BinaryCounts(tn=5).precision_interval() is None
    assert BinaryCounts(fn=3).precision is None and BinaryCounts(fn=3).recall == 0.0
    assert BinaryCounts().as_dict()["precision"] is None


def test_counts_add_and_serialise() -> None:
    total = BinaryCounts(tp=1) + BinaryCounts(fp=1, tn=2)
    assert (total.tp, total.fp, total.tn, total.fn) == (1, 1, 2, 0)
    assert total.as_dict()["n"] == 4


def test_wilson_interval_is_a_valid_proportion_interval() -> None:
    low, high = wilson_interval(8, 10)  # type: ignore[misc]
    assert 0 <= low < 0.8 < high <= 1
    assert wilson_interval(0, 0) is None
    assert wilson_interval(10, 10)[1] == 1.0  # type: ignore[index]
    # A small sample gives a wide interval: 3/3 is far from certain.
    assert wilson_interval(3, 3)[0] < 0.5  # type: ignore[index]


def test_summary_counts_false_failures_and_silent_passes_on_unmeasurable_evidence() -> (
    None
):
    from geoptimiser.validation.__main__ import summarize
    from geoptimiser.validation.evaluate import FixtureEvaluation

    ev = FixtureEvaluation("x")
    ev.state_pairs = [
        ("not_measured", "fail"),  # a defect claimed without evidence
        ("not_applicable", "fail"),
        ("not_measured", "pass"),  # a pass claimed without evidence
        ("not_measured", "not_measured"),
        ("fail", "fail"),
    ]
    summary = summarize([ev])
    assert summary["false_failures_on_unmeasurable"] == 2
    assert summary["silent_passes_on_unmeasurable"] == 1
    assert summary["state_confusion"]["fail -> fail"] == 1
