"""Checks that need extraction detail level 2: viewport, landmarks, links, images, tables,
lists and media. The engine reports ``not_measured`` for older documents."""

import re
from urllib.parse import urlsplit

from geoptimiser.features.checks._common import entities, obs, types_of
from geoptimiser.features.checks.urls import _unreadable
from geoptimiser.features.context import Ctx, has_value, norm, terms
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import (
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
)
from geoptimiser.features.registry import check
from geoptimiser.schemas import PageDocument

# F059's problem text for a missing <main>; the same cause as an F052 failure.
NO_MAIN = "no main landmark"
_STRUCTURAL = ("main", "article", "section", "nav", "header", "footer", "aside")
_PSEUDO_ITEM = re.compile(r"^\s*(?:[-*•·–]|\d{1,2}[.)])\s+\S")
_STEP = re.compile(r"^\s*step\s+\d+", re.I)
_CAMERA = re.compile(r"^(img|dsc|image|photo|pic|screenshot|untitled)[-_ ]?\d*$", re.I)


def _doc(page: PageContext) -> PageDocument:
    assert page.document is not None
    return page.document


def _directives(viewport: str) -> dict[str, str]:
    pairs = (p.split("=", 1) for p in re.split(r"[,;]", viewport.lower()) if "=" in p)
    return {k.strip(): v.strip() for k, v in pairs}


@check("F029", requires="rich_document")
def viewport(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    if doc.viewport is None:
        return failed(
            "No viewport meta tag.",
            (obs(page, "no <meta name=viewport>"),),
            None,
            "width=device-width",
        )
    values = _directives(doc.viewport)
    problems = []
    if values.get("width") != "device-width":
        problems.append("width is not device-width")
    if values.get("user-scalable") in ("no", "0"):
        problems.append("zoom is disabled (user-scalable)")
    try:
        if float(values.get("maximum-scale", "5")) <= 1:
            problems.append("zoom is limited (maximum-scale <= 1)")
    except ValueError:
        problems.append("maximum-scale is not a number")
    if problems:
        return failed(
            "; ".join(problems).capitalize() + ".",
            (obs(page, f"viewport: {doc.viewport}"),),
            doc.viewport,
            "width=device-width, zoom allowed",
        )
    return passed(
        "The viewport is configured for devices.",
        doc.viewport,
        "width=device-width, zoom allowed",
        (obs(page, f"viewport: {doc.viewport}"),),
    )


@check("F052", requires="rich_document")
def main_content_signal(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    kinds = sorted({m.kind for m in doc.landmarks if m.kind in ("main", "article")})
    if kinds:
        return passed(
            f"Main content is marked ({', '.join(kinds)}).", kinds, "main or article"
        )
    return failed(
        "No <main> or <article> landmark.",
        (obs(page, f"{len(doc.landmarks)} landmarks, none main/article"),),
        [],
        "main or article",
    )


@check("F053", requires="rich_document")
def navigation_ratio(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    if not doc.text.strip():
        return not_applicable("The page has no text.")
    if not doc.landmarks:
        return not_measured(
            "The page has no landmarks, so navigation cannot be separated from content."
        )
    ratio = min(doc.boilerplate_chars / max(len(doc.text), 1), 1.0)
    limit = ctx.config.max_boilerplate_ratio
    if ratio <= limit:
        return passed(
            f"{ratio:.0%} of the text is navigation or boilerplate.",
            round(ratio, 3),
            f"<= {limit}",
        )
    return failed(
        f"{ratio:.0%} of the text is navigation or boilerplate (limit {limit:.0%}).",
        (
            obs(
                page,
                f"{doc.boilerplate_chars} of {len(doc.text)} characters in boilerplate regions",
            ),
        ),
        round(ratio, 3),
        f"<= {limit}",
    )


@check("F054", requires="rich_document")
def hidden_content(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    total = doc.hidden_chars + len(doc.text)
    if total == 0:
        return not_applicable("The page has no text.")
    ratio = doc.hidden_chars / total
    limit = ctx.config.max_hidden_ratio
    if ratio <= limit:
        return passed(
            f"{ratio:.0%} of the text is hidden.", round(ratio, 3), f"<= {limit}"
        )
    return failed(
        f"{ratio:.0%} of the text is hidden (limit {limit:.0%}).",
        (obs(page, f"{doc.hidden_chars} hidden characters, {len(doc.text)} visible"),),
        round(ratio, 3),
        f"<= {limit}",
    )


@check("F055", requires="rich_document")
def semantic_html(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    counts = {k: v for k, v in doc.semantic_counts.items() if k in _STRUCTURAL}
    needed = ctx.config.min_semantic_kinds
    if len(counts) >= needed:
        return passed(
            f"{len(counts)} kinds of semantic elements.", counts, f">= {needed} kinds"
        )
    return failed(
        f"Only {len(counts)} kind(s) of semantic structural elements (minimum {needed}).",
        (obs(page, f"semantic elements: {counts or 'none'}"),),
        counts,
        f">= {needed} kinds",
    )


@check("F056", requires="rich_document")
def table_structure(page: PageContext, ctx: Ctx) -> Outcome:
    tables = [t for t in _doc(page).tables if not t.presentational]
    if not tables:
        return not_applicable("The page has no data tables.")
    bad = [
        t
        for t in tables
        if t.row_count >= 2 and t.column_count >= 2 and not t.has_header_cells
    ]
    if not bad:
        return passed(
            f"{len(tables)} data table(s) have header cells or are too small to need them.",
            [],
            [],
        )
    return failed(
        f"{len(bad)} data table(s) have no header cells.",
        tuple(
            obs(
                page,
                f"table {t.row_count}x{t.column_count}, no <th>"
                + (f', caption "{t.caption}"' if t.caption else ""),
            )
            for t in bad[:5]
        ),
        [{"rows": t.row_count, "columns": t.column_count} for t in bad],
        [],
    )


@check("F057", requires="rich_document")
def list_structure(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    pseudo = [line for line in doc.text.split("\n") if _PSEUDO_ITEM.match(line)]
    minimum = ctx.config.pseudo_list_min_lines
    if len(pseudo) < minimum:
        return not_applicable("The text has no list-like lines.")
    real = max((b.item_count for b in doc.lists if not b.in_navigation), default=0)
    if real >= minimum:
        return passed(
            "The page also uses real list markup.",
            {"pseudo_lines": len(pseudo), "real_items": real},
            "real lists",
        )
    return failed(
        f"{len(pseudo)} list-like text lines but no real list.",
        tuple(obs(page, f"list-like line: {line}") for line in pseudo[:3]),
        {"pseudo_lines": len(pseudo), "real_items": real},
        "real lists",
    )


@check("F058", requires="rich_document")
def anchor_text(page: PageContext, ctx: Ctx) -> Outcome:
    anchors = _doc(page).anchors
    if not anchors:
        return not_applicable("The page has no followable anchors.")
    generic = {norm(g) for g in ctx.config.generic_anchor_texts}
    bad = [a for a in anchors if not a.text.strip() or norm(a.text) in generic]
    if not bad:
        return passed("All anchors have descriptive text.", [], [])
    return failed(
        f"{len(bad)} of {len(anchors)} anchors have empty or generic text.",
        tuple(
            obs(page, f'anchor "{a.text or "(empty)"}" -> {a.href}') for a in bad[:5]
        ),
        [a.text for a in bad],
        [],
    )


@check("F059", requires="rich_document", version=2)
def landmark_accessibility(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    landmarks = doc.landmarks
    problems: list[str] = []
    mains = [m for m in landmarks if m.kind == "main"]
    cut = doc.source_truncated or "landmarks" in doc.truncated_fields
    if not mains and not cut:  # in a cut document the <main> may lie beyond the cut
        problems.append(NO_MAIN)
    elif len(mains) > 1:
        problems.append(f"{len(mains)} main landmarks")
    for kind in ("navigation", "complementary"):
        group = [m for m in landmarks if m.kind == kind]
        if len(group) > 1 and any(not m.labelled for m in group):
            problems.append(f"{len(group)} {kind} landmarks without distinct labels")
    if not problems:
        return passed("Landmarks are present and distinguishable.", [], [])
    return failed(
        "; ".join(problems).capitalize() + ".",
        (obs(page, "landmarks: " + (", ".join(m.kind for m in landmarks) or "none")),),
        problems,
        [],
    )


@check("F077", requires="rich_document")
def contextual_links(page: PageContext, ctx: Ctx) -> Outcome:
    anchors = _doc(page).anchors
    if not anchors:
        return not_applicable("The page has no followable anchors.")
    content = sum(1 for a in anchors if a.region == "content")
    ratio = content / len(anchors)
    minimum = ctx.config.min_contextual_links
    observed = {"content": content, "total": len(anchors), "ratio": round(ratio, 3)}
    if content >= minimum:
        return passed(
            f"{content} of {len(anchors)} links are in body content.",
            observed,
            f">= {minimum}",
        )
    return failed(
        "No link sits in body content; all are navigation or boilerplate.",
        (obs(page, f"{len(anchors)} anchors, all in navigation regions"),),
        observed,
        f">= {minimum}",
    )


@check("F078", requires="rich_document")
def anchor_relevance(page: PageContext, ctx: Ctx) -> Outcome:
    mismatched, checked = [], 0
    for anchor in _doc(page).anchors:
        if anchor.region != "content" or not anchor.internal:
            continue
        target = ctx.page_for(anchor.href)
        words = terms(anchor.text)
        if target is None or target.document is None or not words:
            continue
        label = terms(
            " ".join(
                [
                    target.document.title or "",
                    *(h.text for h in target.document.headings if h.level == 1),
                ]
            )
        )
        if not label:
            continue
        checked += 1
        if not words & label:
            mismatched.append((anchor, target))
    if checked == 0:
        return not_applicable(
            "No internal content anchor points to a crawled, titled page."
        )
    if not mismatched:
        return passed(f"{checked} anchor(s) share terms with their targets.", [], [])
    return failed(
        f"{len(mismatched)} of {checked} anchors share no terms with their target page.",
        tuple(
            obs(page, f'anchor "{a.text}" -> {t.url} (title "{t.document.title}")')
            for a, t in mismatched[:5]
            if t.document
        ),  # type: ignore[union-attr]
        [a.text for a, _ in mismatched],
        [],
    )


def _visible_images(page: PageContext):  # type: ignore[no-untyped-def]
    return [i for i in _doc(page).images]


@check("F081", requires="rich_document")
def image_alt(page: PageContext, ctx: Ctx) -> Outcome:
    images = _visible_images(page)
    if not images:
        return not_applicable("The page has no images.")
    missing = [i for i in images if i.alt is None and not i.decorative]
    if not missing:
        return passed(
            f"All {len(images)} images have alt text or are decorative.",
            {"images": len(images), "missing": 0},
            0,
        )
    return failed(
        f"{len(missing)} of {len(images)} images have no alt attribute.",
        tuple(
            obs(page, f"<img> without alt: {i.src or '(no src)'}") for i in missing[:5]
        ),
        {"images": len(images), "missing": len(missing)},
        0,
    )


def _filename_stem(src: str) -> str:
    name = urlsplit(src).path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


@check("F082", requires="rich_document")
def image_filenames(page: PageContext, ctx: Ctx) -> Outcome:
    named = [
        (i, _filename_stem(i.src))
        for i in _visible_images(page)
        if i.src and i.src.startswith("http")
    ]
    named = [(i, stem) for i, stem in named if stem]
    if not named:
        return not_applicable("No image has a file name to judge.")
    limit = ctx.config.max_url_segment_chars
    bad = [
        (i, stem)
        for i, stem in named
        if _CAMERA.match(stem) or _unreadable(stem, limit)
    ]
    if not bad:
        return passed("Image file names look descriptive.", [], [])
    return failed(
        f"{len(bad)} of {len(named)} image file names look opaque.",
        tuple(obs(page, f"image file: {i.src}") for i, _ in bad[:5]),
        [s for _, s in bad],
        [],
    )


@check("F083", requires="rich_document")
def image_dimensions(page: PageContext, ctx: Ctx) -> Outcome:
    images = [i for i in _visible_images(page) if i.src and i.src != "data:"]
    if not images:
        return not_applicable("The page has no images with a URL.")
    missing = [i for i in images if i.width is None or i.height is None]
    if not missing:
        return passed(
            f"All {len(images)} images declare width and height.",
            {"images": len(images), "missing": 0},
            0,
        )
    return failed(
        f"{len(missing)} of {len(images)} images lack width or height.",
        tuple(
            obs(page, f"<img> size {i.width}x{i.height}: {i.src}") for i in missing[:5]
        ),
        {"images": len(images), "missing": len(missing)},
        0,
    )


@check("F084", requires="rich_document")
def image_loading(page: PageContext, ctx: Ctx) -> Outcome:
    content = [
        i for i in _visible_images(page) if not i.decorative and not i.in_navigation
    ]
    if not content:
        return not_applicable("The page has no content images.")
    first = content[0]
    if first.loading == "lazy":
        return failed(
            "The first content image is lazy-loaded.",
            (obs(page, f"loading=lazy on first image: {first.src}"),),
            "lazy",
            "eager",
        )
    return passed(
        "The first content image is not lazy-loaded.",
        first.loading or "default",
        "eager",
    )


def _has_transcript(doc: PageDocument) -> bool:
    haystack = [h.text for h in doc.headings] + [a.text for a in doc.anchors]
    return (
        any("transcript" in t.lower() for t in haystack)
        or "transcript" in doc.text.lower()
    )


def _media_transcript(page: PageContext, kinds: set[str], label: str) -> Outcome:
    doc = _doc(page)
    if not [m for m in doc.media if m.kind in kinds]:
        return not_applicable(f"The page has no {label}.")
    if _has_transcript(doc):
        return passed("A transcript is mentioned.", True, True)
    return failed(
        f"The page has {label} but no transcript.",
        (obs(page, f"{label} present; no 'transcript' heading, link or text"),),
        False,
        True,
    )


@check("F086", requires="rich_document")
def video_transcript(page: PageContext, ctx: Ctx) -> Outcome:
    return _media_transcript(page, {"video", "video_embed"}, "video")


@check("F089", requires="rich_document")
def audio_transcript(page: PageContext, ctx: Ctx) -> Outcome:
    return _media_transcript(page, {"audio"}, "audio")


@check("F087", requires="rich_document")
def video_captions(page: PageContext, ctx: Ctx) -> Outcome:
    media = _doc(page).media
    videos = [m for m in media if m.kind == "video"]
    embeds = [m for m in media if m.kind == "video_embed"]
    if not videos and not embeds:
        return not_applicable("The page has no video.")
    if not videos:
        return not_measured(
            "Only embedded players are present; their captions cannot be seen from the page."
        )
    bare = [m for m in videos if not m.has_captions]
    if bare:
        return failed(
            f"{len(bare)} of {len(videos)} <video> elements have no captions track.",
            tuple(
                obs(page, f"<video> without captions track: {m.src or '(no src)'}")
                for m in bare[:5]
            ),
            {"videos": len(videos), "without_captions": len(bare)},
            0,
        )
    return passed(
        f"All {len(videos)} <video> elements have a captions track.",
        {"videos": len(videos), "without_captions": 0},
        0,
    )


@check("F088", requires="rich_document")
def video_metadata(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    if not [m for m in doc.media if m.kind in ("video", "video_embed")]:
        return not_applicable("The page has no video.")
    required = ctx.config.entity_properties.get("VideoObject", ())
    objects = [e for e in entities(doc) if "VideoObject" in types_of(e)]
    if not objects:
        return failed(
            "The page has video but no VideoObject structured data.",
            (obs(page, "video present; no VideoObject"),),
            "missing",
            "VideoObject",
        )
    missing = [
        f"VideoObject lacks {', '.join(p)}"
        for e in objects
        if (p := [k for k in required if not has_value(e.get(k))])
    ]
    if missing:
        return failed(
            "; ".join(missing[:3]) + ".",
            (obs(page, "; ".join(missing[:3])),),
            missing,
            [],
        )
    return passed("VideoObject structured data is complete.", [], [])


def _page_label(doc: PageDocument) -> str:
    h1 = next((h.text for h in doc.headings if h.level == 1), "")
    return " " + norm((doc.title or "") + " " + h1) + " "


@check("F094", requires="rich_document")
def procedural_steps(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    label = _page_label(doc).strip()
    if not any(label.startswith(p) for p in ctx.config.how_to_prefixes):
        return not_applicable("The page does not look like a how-to page.")
    ordered = [
        b
        for b in doc.lists
        if b.kind == "ol" and not b.in_navigation and b.item_count >= 2
    ]
    steps = sum(1 for line in doc.text.split("\n") if _STEP.match(line))
    if ordered or steps >= 2:
        return passed(
            "The steps are marked up in order.",
            {"ordered_lists": len(ordered), "step_lines": steps},
            "ordered steps",
        )
    return failed(
        "A how-to page without an ordered list or 'Step N' markers.",
        (obs(page, f'how-to page "{doc.title}" has no ordered steps'),),
        {"ordered_lists": 0, "step_lines": steps},
        "ordered steps",
    )


@check("F095", requires="rich_document")
def comparison_structure(page: PageContext, ctx: Ctx) -> Outcome:
    doc = _doc(page)
    label = _page_label(doc)
    if not any(term in label for term in ctx.config.comparison_terms):
        return not_applicable("The page does not look like a comparison page.")
    tables = [
        t
        for t in doc.tables
        if not t.presentational and t.row_count >= 2 and t.column_count >= 2
    ]
    if tables:
        return passed(f"{len(tables)} comparison table(s).", len(tables), ">= 1 table")
    return failed(
        "A comparison page without a data table.",
        (obs(page, f'comparison page "{doc.title}" has no data table'),),
        0,
        ">= 1 table",
    )
