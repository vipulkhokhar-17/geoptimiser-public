"""Metric values below were computed by hand (see the comments)."""

import pytest

from geoptimiser.benchmark import metrics

RANKING = ["a", "b", "c", "d", "e"]
GRADES = {"b": 3, "d": 1, "z": 2}  # z is relevant but never retrieved


def test_recall_at_k() -> None:
    assert metrics.recall_at_k(RANKING, GRADES, 1) == 0.0
    assert metrics.recall_at_k(RANKING, GRADES, 2) == pytest.approx(
        1 / 3
    )  # b of {b,d,z}
    assert metrics.recall_at_k(RANKING, GRADES, 4) == pytest.approx(2 / 3)  # b, d
    assert metrics.recall_at_k(RANKING, GRADES, 100) == pytest.approx(
        2 / 3
    )  # z is never found


def test_hit_rate_at_k() -> None:
    assert metrics.hit_rate_at_k(RANKING, GRADES, 1) == 0.0
    assert metrics.hit_rate_at_k(RANKING, GRADES, 2) == 1.0


def test_reciprocal_rank() -> None:
    assert metrics.reciprocal_rank(RANKING, GRADES) == 0.5  # first relevant at rank 2
    assert metrics.reciprocal_rank(["b"], GRADES) == 1.0
    assert (
        metrics.reciprocal_rank(["x", "y"], GRADES) == 0.0
    )  # retrieved, none relevant
    assert metrics.reciprocal_rank([], GRADES) == 0.0  # retrieved nothing


def test_ndcg_hand_computed() -> None:
    # DCG@5  = (2^3-1)/log2(3) + (2^1-1)/log2(5)             = 4.847184833
    # IDCG@5 = 7/log2(2) + 3/log2(3) + 1/log2(4)              = 9.392789261
    assert metrics.ndcg_at_k(RANKING, GRADES, 5) == pytest.approx(0.5160538258)
    # k=2: DCG = 7/log2(3) = 4.416508; IDCG = 7 + 3/log2(3) = 8.892789
    assert metrics.ndcg_at_k(RANKING, GRADES, 2) == pytest.approx(0.4966392597)


def test_perfect_ranking_scores_one() -> None:
    assert metrics.ndcg_at_k(["b", "z", "d"], GRADES, 3) == pytest.approx(1.0)


def test_ndcg_k_one_is_normalised_by_the_ideal_first_item() -> None:
    assert metrics.ndcg_at_k(["b"], GRADES, 1) == pytest.approx(1.0)  # 7 / 7
    assert metrics.ndcg_at_k(["z"], GRADES, 1) == pytest.approx(
        3 / 7
    )  # gain(2)=3 vs ideal 7


def test_binary_labels() -> None:
    grades = {"a": 1, "c": 1}
    # DCG@3 = 1/log2(2) + 1/log2(4) = 1.5 ; IDCG@3 = 1 + 1/log2(3) = 1.6309297536
    assert metrics.ndcg_at_k(["a", "b", "c"], grades, 3) == pytest.approx(
        1.5 / 1.6309297536
    )


def test_grade_zero_is_not_relevant_but_is_not_a_gain() -> None:
    grades = {"a": 0, "b": 2}
    assert metrics.recall_at_k(["a", "b"], grades, 1) == 0.0
    assert metrics.reciprocal_rank(["a", "b"], grades) == 0.5


def test_duplicates_in_a_ranking_count_once() -> None:
    assert metrics.dedupe(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
    assert metrics.reciprocal_rank(["x", "x", "b"], GRADES) == 0.5  # b is rank 2, not 3
    assert metrics.recall_at_k(["b", "b", "b"], {"b": 1}, 3) == 1.0


def test_queries_without_relevant_items_are_undefined_not_zero() -> None:
    for fn in (
        lambda: metrics.recall_at_k(RANKING, {}, 3),
        lambda: metrics.hit_rate_at_k(RANKING, {"a": 0}, 3),
        lambda: metrics.reciprocal_rank(RANKING, {}),
        lambda: metrics.ndcg_at_k(RANKING, {"a": 0}, 3),
    ):
        with pytest.raises(ValueError, match="no relevant items"):
            fn()


@pytest.mark.parametrize("k", [0, -1, 1.5, True, "3"])
def test_invalid_k(k: object) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        metrics.recall_at_k(RANKING, GRADES, k)  # type: ignore[arg-type]


def test_percentile_nearest_rank() -> None:
    sample = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert metrics.percentile(sample, 50) == 30.0
    assert metrics.percentile(sample, 95) == 50.0
    assert metrics.percentile(sample, 0) == 10.0
    assert metrics.percentile([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        metrics.percentile([], 50)
