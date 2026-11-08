"""Run the retrieval comparison with the real embedding model on the fixtures.

    python -m tests.retrieval.semantic.run_benchmark --out build/semantic_eval

Writes one ``<name>.retrieval_eval.json`` per query set and prints a table. All three
corpora are synthetic fixtures: the numbers show how the methods behave on these
constructed cases, not how they would do on real sites. Exits 2 (writing nothing) if
the optional extra or the model is unavailable; it never substitutes another embedder.
"""

import argparse
import sys
from pathlib import Path

from geoptimiser.benchmark import load_judgment_set, load_query_set
from geoptimiser.retrieval import (
    EmbedderSettings,
    EmbeddingError,
    Retriever,
    TermCoverageReranker,
    compare_retrieval,
    describe,
    load_settings,
    write_comparison,
)
from geoptimiser.retrieval.settings import build_embedder
from tests.retrieval.conftest import FIXTURES, chunks_from_pages

HERE = Path(__file__).parent
RUNS = (
    (
        "plumbing",
        FIXTURES / "corpus.json",
        FIXTURES / "queryset.json",
        FIXTURES / "judgments.json",
    ),
    (
        "paraphrase",
        HERE / "corpus.json",
        HERE / "paraphrase_queries.json",
        HERE / "paraphrase_judgments.json",
    ),
    (
        "lexical_control",
        HERE / "corpus.json",
        HERE / "control_queries.json",
        HERE / "control_judgments.json",
    ),
)
METRICS = ("mrr", "hit_rate@1", "hit_rate@3", "recall@10", "ndcg@10")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--settings", type=Path, default=Path("configs/retrieval.json"))
    parser.add_argument(
        "--allow-test-embedder",
        action="store_true",
        help="use the word-overlap hashing embedder instead of the real model "
        "(plumbing only: dense, hybrid and rerank results are then NOT semantic)",
    )
    args = parser.parse_args(argv)
    settings = load_settings(args.settings)
    if args.allow_test_embedder:
        settings = settings.model_copy(
            update={"embedder": EmbedderSettings(kind="hashing-test")}
        )
    try:
        embedder = build_embedder(
            settings.embedder, allow_test_embedder=args.allow_test_embedder
        )  # the real model unless explicitly overridden
    except EmbeddingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    reranker = TermCoverageReranker()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        for name, corpus, queries, judgments in RUNS:
            retriever = Retriever(
                chunks_from_pages(corpus),
                settings.retrieval,
                embedder=embedder,
                reranker=reranker,
                require_semantic=not args.allow_test_embedder,
            )
            cmp = compare_retrieval(
                load_query_set(queries), load_judgment_set(judgments), retriever
            )
            write_comparison(args.out / f"{name}.retrieval_eval.json", cmp)
            print(f"\n== {name}  ({cmp.n_chunks} chunks, queries evaluated per mode)")
            print(f"{'mode':14s}" + "".join(f"{m:>12s}" for m in METRICS) + "   p50 ms")
            for r in cmp.results:
                means = r.report.means if r.report else None
                row = (
                    "".join(f"{means[m]:12.3f}" for m in METRICS) if means else r.status
                )
                lat = f"{r.latency.p50_ms:9.2f}" if r.latency else ""
                print(f"{r.mode:14s}{row}{lat}")
        d = describe(embedder)
        print(
            f"\nmodel={d.model_id} revision={d.revision} dims={d.dimensions} "
            f"normalized={d.normalized} similarity={d.similarity} libs={d.libraries}"
        )
    except EmbeddingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
