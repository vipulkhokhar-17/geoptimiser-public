"""Binary-classification metrics with honest handling of empty denominators."""

import math
from dataclasses import dataclass


def wilson_interval(
    successes: int, total: int, z: float = 1.96
) -> tuple[float, float] | None:
    """Wilson score interval for a proportion; ``None`` when ``total`` is 0."""
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    margin /= denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass(frozen=True)
class BinaryCounts:
    """Confusion counts for one feature; the positive class is a *detected defect*."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def precision(self) -> float | None:
        """TP / (TP + FP); ``None`` (undefined) when nothing was predicted positive."""
        return None if self.tp + self.fp == 0 else self.tp / (self.tp + self.fp)

    @property
    def recall(self) -> float | None:
        """TP / (TP + FN); ``None`` (undefined) when there were no true positives."""
        return None if self.tp + self.fn == 0 else self.tp / (self.tp + self.fn)

    def precision_interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.tp, self.tp + self.fp)

    def recall_interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.tp, self.tp + self.fn)

    def __add__(self, other: "BinaryCounts") -> "BinaryCounts":
        return BinaryCounts(
            self.tp + other.tp,
            self.fp + other.fp,
            self.tn + other.tn,
            self.fn + other.fn,
        )

    def as_dict(self) -> dict[str, object]:
        def rounded(v: float | None) -> float | None:
            return None if v is None else round(v, 4)

        def interval(v: tuple[float, float] | None) -> list[float] | None:
            return None if v is None else [round(v[0], 4), round(v[1], 4)]

        return {
            "tp": self.tp,
            "fp": self.fp,
            "tn": self.tn,
            "fn": self.fn,
            "n": self.n,
            "precision": rounded(self.precision),
            "precision_ci95": interval(self.precision_interval()),
            "recall": rounded(self.recall),
            "recall_ci95": interval(self.recall_interval()),
        }
