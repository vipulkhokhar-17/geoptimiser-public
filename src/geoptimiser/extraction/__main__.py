"""CLI: ``python -m geoptimiser.extraction --crawl-dir runs/example``."""

import argparse
from pathlib import Path

from geoptimiser.crawler import LocalBodyStore, read_fetches
from geoptimiser.extraction import ExtractionWriter, extract_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract pages from a finished crawl.")
    parser.add_argument("--crawl-dir", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, help="output directory (default: <crawl-dir>/extraction)"
    )
    args = parser.parse_args(argv)

    fetches = read_fetches(args.crawl_dir / "fetches.jsonl")
    store = LocalBodyStore(args.crawl_dir / "bodies")
    with ExtractionWriter(args.out or args.crawl_dir / "extraction") as sink:
        result = extract_all(fetches, store, sink=sink)
    print(
        f"{len(result.documents)} documents, {len(result.failures)} failures, "
        f"{len(result.skipped)} skipped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
