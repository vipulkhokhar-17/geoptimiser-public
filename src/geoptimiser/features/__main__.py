"""CLI.

* ``python -m geoptimiser.features --crawl-dir runs/example`` runs the audit checks
  on a finished crawl and extraction and writes ``<crawl-dir>/features/``.
* ``python -m geoptimiser.features --export`` regenerates the checked-in catalog
  JSON/Markdown and the scoring policy.
"""

import argparse
from pathlib import Path

from geoptimiser.features.audit import run_audit, write_artifacts
from geoptimiser.features.export import catalog_json, catalog_markdown, scoring_json
from geoptimiser.features.inputs import load_inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run GEO feature checks on a crawl.")
    parser.add_argument("--crawl-dir", type=Path)
    parser.add_argument("--extraction-dir", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument(
        "--export", action="store_true", help="regenerate catalog files"
    )
    args = parser.parse_args(argv)

    if args.export:
        root = Path(__file__).resolve().parents[3]
        (root / "configs" / "feature_catalog.json").write_text(
            catalog_json(), encoding="utf-8"
        )
        (root / "configs" / "scoring.json").write_text(scoring_json(), encoding="utf-8")
        (root / "docs" / "FEATURE_CATALOG.md").write_text(
            catalog_markdown(), encoding="utf-8"
        )
        print(
            "exported configs/feature_catalog.json, configs/scoring.json, docs/FEATURE_CATALOG.md"
        )
        return 0
    if args.crawl_dir is None:
        parser.error("--crawl-dir is required (or use --export)")
    run = run_audit(load_inputs(args.crawl_dir, args.extraction_dir))
    write_artifacts(run, args.out or args.crawl_dir / "features")
    overall = run.scores.overall
    print(
        f"{len(run.results)} results, {len(run.findings)} findings; overall score "
        f"{overall.score} (feature coverage {overall.feature_coverage}, "
        f"reportable={overall.reportable})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
