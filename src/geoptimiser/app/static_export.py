"""Export the bundled UI as a static site (for GitHub Pages) with a configurable API base.

``python -m geoptimiser.app.static_export --out site --api-base https://api.geoptimiser.me
--domain geoptimiser.me``

The exported site is the same UI files the backend serves (page, script, styles, two
self-hosted OFL fonts and their licence), with relative asset paths
(it is hosted at the root of its own domain, but relative paths also survive a sub-path),
a generated ``config.js`` that holds the API base, a Content-Security-Policy ``<meta>``
that permits requests only to this site and that one API origin, ``CNAME`` and
``.nojekyll``. It contains no secrets: the API base is public by nature and nothing else is
configured here.
"""

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

from geoptimiser.app.config import validate_origin
from geoptimiser.schemas import normalize_domain

UI_DIR = Path(__file__).parent / "ui"
FILES = (
    "app.js",
    "style.css",
    "hanken-grotesk.woff2",
    "jetbrains-mono.woff2",
    "FONTS-LICENSE.txt",
)
DEFAULT_API_BASE = "https://api.geoptimiser.me"
DEFAULT_DOMAIN = "geoptimiser.me"


def csp(api_base: str) -> str:
    connect = "'self'" + (f" {api_base}" if api_base else "")
    return (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        f"connect-src {connect}; img-src 'self' data:; base-uri 'none'; form-action 'none'"
    )


def _attr(value: str) -> str:
    """Escape for a double-quoted attribute (apostrophes are legal and kept)."""
    return html.escape(value, quote=False).replace('"', "&quot;")


def render_index(source: str, api_base: str) -> str:
    """The backend-served index.html turned into a root-relative-free static page."""
    page = re.sub(r'(href|src)="/ui/', r'\1="', source)
    if '"/ui/' in page or "'/ui/" in page:
        raise ValueError("index.html still contains an absolute /ui/ path")
    meta = (
        f'<meta http-equiv="Content-Security-Policy" content="{_attr(csp(api_base))}">\n'
        '<meta name="referrer" content="no-referrer">\n'
    )
    marker = '<meta name="viewport"'
    if marker not in page:
        raise ValueError("index.html has no viewport meta to anchor the CSP meta")
    return page.replace(marker, meta + marker, 1)


def export_site(
    out: Path, *, api_base: str = DEFAULT_API_BASE, domain: str | None = DEFAULT_DOMAIN
) -> list[str]:
    """Write the static site into the empty or missing directory ``out``."""
    base = validate_origin(api_base) if api_base else ""
    host = normalize_domain(domain) if domain else None
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(
        render_index((UI_DIR / "index.html").read_text(encoding="utf-8"), base),
        encoding="utf-8",
    )
    for name in FILES:
        shutil.copyfile(UI_DIR / name, out / name)
    (out / "config.js").write_text(
        f"window.GEOPTIMISER_CONFIG = {json.dumps({'apiBase': base})};\n",
        encoding="utf-8",
    )
    (out / ".nojekyll").write_text("", encoding="utf-8")
    if host:
        (out / "CNAME").write_text(host + "\n", encoding="utf-8")
    return sorted(p.name for p in out.iterdir())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m geoptimiser.app.static_export", description=__doc__
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help="backend origin, or '' for same-origin",
    )
    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help="custom domain for the CNAME file ('' to omit)",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace a non-empty output directory"
    )
    args = parser.parse_args(argv)
    try:
        if args.force and args.out.exists():
            shutil.rmtree(args.out)
        files = export_site(
            args.out, api_base=args.api_base, domain=args.domain or None
        )
    except (ValueError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"exported {len(files)} files to {args.out}: {', '.join(files)}")
    print(f"API base: {args.api_base or '(same origin)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
