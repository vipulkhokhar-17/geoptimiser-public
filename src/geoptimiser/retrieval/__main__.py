"""Compare retrieval modes on stored chunks: ``python -m geoptimiser.retrieval``."""

import argparse
import sys
from pathlib import Path

from geoptimiser.benchmark import DatasetError, load_judgment_set, load_query_set
from geoptimiser.benchmark.evaluate import DatasetMismatch
from geoptimiser.chunking import read_chunks
from geoptimiser.retrieval.dense import EmbeddingError
from geoptimiser.retrieval.evaluate import compare_retrieval, write_comparison
from geoptimiser.retrieval.rerank import TermCoverageReranker
from geoptimiser.retrieval.settings import SettingsError, build_retriever, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m geoptimiser.retrieval")
    parser.add_argument("--chunks", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--judgments", type=Path, required=True)
    parser.add_argument("--settings", type=Path, default=Path("configs/retrieval.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--allow-test-embedder",
        action="store_true",
        help="permit the word-overlap test embedder (plumbing checks only)",
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.settings)
        queries = load_query_set(args.queries)
        judgments = load_judgment_set(args.judgments)
        chunks = read_chunks(args.chunks)
        retriever = build_retriever(
            chunks,
            settings,
            reranker=TermCoverageReranker(),
            allow_test_embedder=args.allow_test_embedder,
        )
        comparison = compare_retrieval(queries, judgments, retriever)
        write_comparison(args.out, comparison)
    except (SettingsError, DatasetError, DatasetMismatch, EmbeddingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for result in comparison.results:
        means = result.report.means if result.report else None
        summary = (
            f"ndcg@10={means['ndcg@10']:.3f} mrr={means['mrr']:.3f}"
            if means
            else result.reason or result.status
        )
        print(f"{result.mode:14s} {result.status:13s} {summary}")
    for note in comparison.notes:
        print(f"note: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
