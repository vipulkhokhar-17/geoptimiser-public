"""Build benchmarks/corpus/manifest.json from pages already in this repository.

The labels come from an INDEPENDENT parser (lxml) and independently written rules; they
are marked ``kind: oracle``. They are not human labels and these pages are not
real-world pages. Run from the repository root with lxml installed (it is not a project
dependency):

    python benchmarks/build_initial_corpus.py

The manifest is checked in, so the corpus evaluation itself needs no lxml.
"""

import json
import re
import shutil
from datetime import date
from pathlib import Path

import lxml
import lxml.html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmarks" / "corpus"
ORACLE = f"oracle:lxml {lxml.__version__}"
SOURCES = {
    # snapshot id: (repo path, page type, note)
    "demo_before_index": (
        "src/geoptimiser/demo/site/before/index.html",
        "marketing home (demo)",
    ),
    "demo_before_about": (
        "src/geoptimiser/demo/site/before/about.html",
        "marketing about (demo)",
    ),
    "demo_before_pricing": (
        "src/geoptimiser/demo/site/before/pricing.html",
        "pricing (demo)",
    ),
    "demo_before_faq": ("src/geoptimiser/demo/site/before/faq.html", "faq (demo)"),
    "demo_before_blog": (
        "src/geoptimiser/demo/site/before/blog-how-we-price.html",
        "blog article (demo)",
    ),
    "demo_after_index": (
        "src/geoptimiser/demo/site/after/index.html",
        "marketing home, fixed (demo)",
    ),
    "demo_after_about": (
        "src/geoptimiser/demo/site/after/about.html",
        "marketing about, fixed (demo)",
    ),
    "fx_full_page": (
        "tests/extraction/fixtures/full_page.html",
        "complete page (fixture)",
    ),
    "fx_rich_page": ("tests/extraction/fixtures/rich_page.html", "rich page (fixture)"),
    "fx_malformed": (
        "tests/extraction/fixtures/malformed.html",
        "malformed markup (fixture)",
    ),
    "fx_rich_malformed": (
        "tests/extraction/fixtures/rich_malformed.html",
        "malformed rich markup (fixture)",
    ),
    "fx_incomplete": (
        "tests/extraction/fixtures/incomplete.html",
        "fragment without head (fixture)",
    ),
    "fx_rich_incomplete": (
        "tests/extraction/fixtures/rich_incomplete.html",
        "rich fragment (fixture)",
    ),
    "fx_empty": ("tests/extraction/fixtures/empty.html", "empty document (fixture)"),
}
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def _first(tree, xpath):  # type: ignore[no-untyped-def]
    found = tree.xpath(xpath)
    return found[0] if found else None


def labels(html: str) -> dict[str, dict[str, object]]:
    """Defect labels from rules written independently of the audit's extractor."""
    try:
        tree = lxml.html.fromstring(html) if html.strip() else None
    except Exception:  # an unparseable document: leave unlabelled
        return {}
    if tree is None:
        return {}
    out: dict[str, bool] = {}
    title = _first(tree, "//title")
    out["F021"] = not (title is not None and (title.text_content() or "").strip())
    desc = _first(
        tree,
        "//meta[translate(@name,'DESCRIPTION','description')='description']/@content",
    )
    out["F024"] = not (desc and desc.strip())
    canon = _first(
        tree,
        "//link[contains(concat(' ',translate(@rel,'CANONICAL','canonical'),' '),"
        "' canonical ')]/@href",
    )
    out["F011"] = not (canon and canon.strip())
    lang = tree.get("lang") if tree.tag == "html" else None
    out["F027"] = not (lang and _LANG.match(lang.strip()))
    viewport = _first(
        tree, "//meta[translate(@name,'VIEWPORT','viewport')='viewport']/@content"
    )
    bad = True
    if viewport:
        kv = dict(
            (p.split("=", 1)[0].strip().lower(), p.split("=", 1)[1].strip().lower())
            for p in re.split(r"[,;]", viewport)
            if "=" in p
        )
        bad = kv.get("width") != "device-width" or kv.get("user-scalable") in (
            "no",
            "0",
        )
        try:
            bad = bad or float(kv.get("maximum-scale", "5")) <= 1
        except ValueError:
            bad = True
    out["F029"] = bad
    h = [
        int(e.tag[1])
        for e in tree.iter()
        if isinstance(e.tag, str) and re.fullmatch(r"h[1-6]", e.tag)
    ]
    empty = any(
        not (e.text_content() or "").strip()
        for e in tree.iter()
        if isinstance(e.tag, str) and re.fullmatch(r"h[1-6]", e.tag)
    )
    out["F035"] = (
        h.count(1) != 1
        or empty
        or any(b > a + 1 for a, b in zip(h, h[1:], strict=False))
    )
    broken = False
    for script in tree.xpath("//script[@type]"):
        if (script.get("type") or "").split(";")[
            0
        ].strip().lower() == "application/ld+json":
            try:
                json.loads(script.text or "")
            except ValueError:
                broken = True
    has_ld = any(
        (s.get("type") or "").split(";")[0].strip().lower() == "application/ld+json"
        for s in tree.xpath("//script[@type]")
    )
    if has_ld:
        out["F061"] = broken
    imgs = tree.xpath("//img")
    if imgs:
        out["F081"] = any(
            i.get("alt") is None
            and (i.get("role") or "").lower() not in ("presentation", "none")
            and (i.get("aria-hidden") or "").lower() != "true"
            for i in imgs
        )
    main = tree.xpath("//main | //article | //*[@role='main'] | //*[@role='article']")
    out["F052"] = not main
    return {
        fid: {
            "defect": d,
            "labeler": ORACLE,
            "kind": "oracle",
            "uncertainty": "oracle written independently of the extractor; "
            "not a human judgment",
        }
        for fid, d in out.items()
    }


def main() -> None:
    snaps = []
    (OUT / "snapshots").mkdir(parents=True, exist_ok=True)
    for sid, (rel, page_type) in SOURCES.items():
        src = ROOT / rel
        dst = OUT / "snapshots" / f"{sid}.html"
        shutil.copyfile(src, dst)
        html = src.read_text(encoding="utf-8")
        snaps.append(
            {
                "snapshot_id": sid,
                "file": f"snapshots/{sid}.html",
                "url": "https://fixture.test/",
                "source": f"repository file {rel}",
                "snapshot_date": date.today().isoformat(),
                "page_type": page_type,
                "real_world": False,
                "response": {
                    "status": 200,
                    "truncated": False,
                    "content_type": "text/html",
                },
                "labels": labels(html),
                "notes": "Synthetic page authored for this repository; "
                "not a real website.",
            }
        )
    manifest = {
        "corpus_version": 1,
        "name": "repository-local initial corpus",
        "description": (
            "Pages already in this repository, labelled by an independent parser. "
            "Exists to exercise the evaluation framework and to cross-check the "
            "extractor; it is not a real-world benchmark."
        ),
        "real_world": False,
        "snapshots": snaps,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(snaps)} snapshots, {sum(len(s['labels']) for s in snaps)} labels"
    )


if __name__ == "__main__":
    main()
