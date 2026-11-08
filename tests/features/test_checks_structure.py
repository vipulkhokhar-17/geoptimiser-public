"""Checks unlocked by rich extraction (detail level 2)."""

import pytest

from geoptimiser.schemas import Heading
from tests.features.builders import audit, page, run, status_of, statuses

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
B = "https://www.example.com/b"

RICH_FEATURES = [
    "F029", "F052", "F053", "F054", "F055", "F056", "F057", "F058", "F059", "F077",
    "F078", "F081", "F082", "F083", "F084", "F086", "F087", "F088", "F089", "F094", "F095",
]  # fmt: skip


def img(src: str = "https://www.example.com/i.png", **kw: object) -> dict:
    return {"src": src, "alt": "A photo", "width": 10, "height": 10, **kw}


def anchor(href: str = A, text: str = "Pricing plans", **kw: object) -> dict:
    return {"href": href, "text": text, "internal": True, "region": "content", **kw}


def landmark(kind: str, **kw: object) -> dict:
    return {"kind": kind, "source": "tag", "labelled": False, **kw}


# --- older documents are not measured, never failed ---------------------------------------


@pytest.mark.parametrize("feature_id", RICH_FEATURES)
def test_level_one_documents_are_not_measured(feature_id: str) -> None:
    old = page(HOME, doc={"detail_level": 1})
    result = run(feature_id, audit(old))[0]
    assert result.status == "not_measured"
    assert "detail level 1" in (result.explanation or "")
    assert result.observed_value is None


@pytest.mark.parametrize("feature_id", RICH_FEATURES)
def test_empty_level_two_documents_never_error_or_fail_on_absence_alone(
    feature_id: str,
) -> None:
    result = run(feature_id, audit(page(HOME)))[0]
    assert result.status != "error"
    if feature_id not in (
        "F029",
        "F052",
        "F055",
        "F059",
    ):  # these assert a page-level signal
        assert result.status in ("not_applicable", "not_measured", "pass"), (
            result.status
        )


def test_f002_uses_followable_anchors_and_falls_back_for_old_documents() -> None:
    nofollow_only = page(
        HOME, doc={"anchors": [anchor(rel=["nofollow"])], "links": [A]}
    )
    result = run("F002", audit(nofollow_only))[0]
    assert result.status == "fail" and result.observed_value == {
        "followable": 0,
        "nofollow": 1,
    }
    followable = page(
        HOME, doc={"anchors": [anchor(), anchor(B, rel=["nofollow"])], "links": [A, B]}
    )
    assert run("F002", audit(followable))[0].status == "pass"
    old = page(HOME, doc={"detail_level": 1, "links": [A]})
    assert run("F002", audit(old))[0].status == "pass"  # only the URL list is known


# --- F029 viewport ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("viewport", "expected"),
    [("width=device-width, initial-scale=1", "pass"), (None, "fail"), ("width=500", "fail"),
     ("width=device-width, user-scalable=no", "fail"), ("width=device-width, maximum-scale=1", "fail"),
     ("width=device-width; initial-scale=1", "pass"), ("width=device-width, maximum-scale=x", "fail")],
)  # fmt: skip
def test_f029_viewport(viewport: str | None, expected: str) -> None:
    assert status_of("F029", page(HOME, doc={"viewport": viewport})) == expected


# --- F052-F055, F059 structure ------------------------------------------------------------------


def test_f052_main_content_signal() -> None:
    assert (
        status_of("F052", page(HOME, doc={"landmarks": [landmark("main")]})) == "pass"
    )
    assert (
        status_of("F052", page(HOME, doc={"landmarks": [landmark("article")]}))
        == "pass"
    )
    assert (
        status_of("F052", page(HOME, doc={"landmarks": [landmark("navigation")]}))
        == "fail"
    )
    assert status_of("F052", page(HOME)) == "fail"


def test_f053_navigation_ratio() -> None:
    text = "x" * 100
    ok = {"text": text, "boilerplate_chars": 20, "landmarks": [landmark("navigation")]}
    assert status_of("F053", page(HOME, doc=ok)) == "pass"
    heavy = {**ok, "boilerplate_chars": 80}
    assert status_of("F053", page(HOME, doc=heavy)) == "fail"
    assert status_of("F053", page(HOME, doc={**ok, "landmarks": []})) == "not_measured"
    assert status_of("F053", page(HOME, doc={"text": ""})) == "not_applicable"
    assert status_of("F053", page(HOME, doc=heavy), max_boilerplate_ratio=0.9) == "pass"


def test_f054_hidden_content() -> None:
    assert (
        status_of("F054", page(HOME, doc={"text": "x" * 90, "hidden_chars": 10}))
        == "pass"
    )
    result = run("F054", audit(page(HOME, doc={"text": "x" * 50, "hidden_chars": 50})))[
        0
    ]
    assert result.status == "fail" and result.observed_value == 0.5
    assert (
        status_of("F054", page(HOME, doc={"text": "", "hidden_chars": 0}))
        == "not_applicable"
    )


def test_f055_semantic_html() -> None:
    rich = {"semantic_counts": {"main": 1, "nav": 2, "figure": 1}}
    assert status_of("F055", page(HOME, doc=rich)) == "pass"  # figure is not structural
    assert status_of("F055", page(HOME, doc={"semantic_counts": {"main": 1}})) == "fail"
    assert (
        status_of(
            "F055",
            page(HOME, doc={"semantic_counts": {"main": 1}}),
            min_semantic_kinds=1,
        )
        == "pass"
    )


def test_f059_landmark_accessibility() -> None:
    good = {"landmarks": [landmark("main"), landmark("navigation")]}
    assert status_of("F059", page(HOME, doc=good)) == "pass"
    assert status_of("F059", page(HOME)) == "fail"
    two_mains = {"landmarks": [landmark("main"), landmark("main")]}
    assert (
        "2 main landmarks"
        in run("F059", audit(page(HOME, doc=two_mains)))[0].observed_value[0]
    )
    navs = {
        "landmarks": [landmark("main"), landmark("navigation"), landmark("navigation")]
    }
    assert status_of("F059", page(HOME, doc=navs)) == "fail"
    labelled = {
        "landmarks": [
            landmark("main"),
            landmark("navigation", labelled=True),
            landmark("navigation", labelled=True),
        ]
    }
    assert status_of("F059", page(HOME, doc=labelled)) == "pass"


# --- tables and lists --------------------------------------------------------------------------------


def table(**kw: object) -> dict:
    return {"row_count": 3, "column_count": 2, "has_header_cells": True, **kw}


def test_f056_table_structure() -> None:
    assert status_of("F056", page(HOME, doc={"tables": [table()]})) == "pass"
    bare = table(has_header_cells=False, caption="Prices")
    result = run("F056", audit(page(HOME, doc={"tables": [bare]})))[0]
    assert result.status == "fail" and "Prices" in result.evidence[0].snippet
    assert (
        status_of(
            "F056",
            page(
                HOME,
                doc={"tables": [table(has_header_cells=False, presentational=True)]},
            ),
        )
        == "not_applicable"
    )
    assert (
        status_of(
            "F056",
            page(HOME, doc={"tables": [table(has_header_cells=False, row_count=1)]}),
        )
        == "pass"
    )
    assert status_of("F056", page(HOME, doc={"tables": []})) == "not_applicable"


def test_f057_list_structure_is_a_heuristic() -> None:
    pseudo = "Intro\n- one\n- two\n- three\nOutro"
    result = run("F057", audit(page(HOME, doc={"text": pseudo})))[0]
    assert result.status == "fail" and result.is_heuristic
    real = {
        "text": pseudo,
        "lists": [{"kind": "ul", "item_count": 3, "items": ["a", "b", "c"]}],
    }
    assert status_of("F057", page(HOME, doc=real)) == "pass"
    menu = {
        "text": pseudo,
        "lists": [{"kind": "ul", "item_count": 9, "in_navigation": True}],
    }
    assert (
        status_of("F057", page(HOME, doc=menu)) == "fail"
    )  # a menu is not the content list
    assert status_of("F057", page(HOME, doc={"text": "1. a\n2. b"})) == "not_applicable"
    assert (
        status_of("F057", page(HOME, doc={"text": "plain prose"})) == "not_applicable"
    )


# --- anchors ------------------------------------------------------------------------------------------


def test_f058_anchor_text() -> None:
    assert (
        status_of("F058", page(HOME, doc={"anchors": [anchor(text="Pricing plans")]}))
        == "pass"
    )
    for bad in ("click here", "Click Here", "", "read more"):
        result = run("F058", audit(page(HOME, doc={"anchors": [anchor(text=bad)]})))[0]
        assert result.status == "fail" and result.is_heuristic, bad
    assert status_of("F058", page(HOME, doc={"anchors": []})) == "not_applicable"


def test_f077_contextual_links() -> None:
    mixed = {"anchors": [anchor(), anchor(B, region="navigation")]}
    result = run("F077", audit(page(HOME, doc=mixed)))[0]
    assert result.status == "pass" and result.observed_value["ratio"] == 0.5
    nav_only = {"anchors": [anchor(region="navigation")]}
    assert status_of("F077", page(HOME, doc=nav_only)) == "fail"
    assert status_of("F077", page(HOME, doc={"anchors": []})) == "not_applicable"


def test_f078_anchor_target_relevance_uses_crawled_targets() -> None:
    target = page(
        A,
        doc={
            "title": "Pricing plans for teams",
            "headings": [Heading(level=1, text="Pricing")],
        },
    )
    related = page(HOME, doc={"anchors": [anchor(A, "our pricing")]})
    assert run("F078", audit(related, target))[0].status == "pass"
    unrelated = page(HOME, doc={"anchors": [anchor(A, "quantum gravity")]})
    result = run("F078", audit(unrelated, target))[0]
    assert result.status == "fail" and result.is_heuristic
    assert statuses("F078", audit(related)) == {
        HOME: "not_applicable"
    }  # target not crawled
    external = page(
        HOME, doc={"anchors": [anchor("https://o.org/", "x y z", internal=False)]}
    )
    assert statuses("F078", audit(external, target))[HOME] == "not_applicable"
    nav = page(
        HOME, doc={"anchors": [anchor(A, "quantum gravity", region="navigation")]}
    )
    assert statuses("F078", audit(nav, target))[HOME] == "not_applicable"


# --- images ---------------------------------------------------------------------------------------------


def test_f081_image_alt() -> None:
    assert status_of("F081", page(HOME, doc={"images": [img()]})) == "pass"
    decorative = img(alt="", decorative=True)
    assert status_of("F081", page(HOME, doc={"images": [decorative]})) == "pass"
    missing = img(alt=None)
    result = run("F081", audit(page(HOME, doc={"images": [img(), missing]})))[0]
    assert result.status == "fail" and result.observed_value == {
        "images": 2,
        "missing": 1,
    }
    assert (
        status_of("F081", page(HOME, doc={"images": [img(alt=None, decorative=True)]}))
        == "pass"
    )  # role=presentation
    assert status_of("F081", page(HOME, doc={"images": []})) == "not_applicable"


def test_f082_image_filenames() -> None:
    good = img("https://www.example.com/img/team-photo.jpg")
    assert status_of("F082", page(HOME, doc={"images": [good]})) == "pass"
    for bad in (
        "IMG_20240101.jpg",
        "DSC0001.png",
        "3f2504e0-4f89-11d3-9a0c-0305e82c3301.png",
        "88271936451.webp",
    ):
        result = run(
            "F082",
            audit(page(HOME, doc={"images": [img(f"https://www.example.com/{bad}")]})),
        )[0]
        assert result.status == "fail" and result.is_heuristic, bad
    assert (
        status_of("F082", page(HOME, doc={"images": [img("data:")]}))
        == "not_applicable"
    )


def test_f083_image_dimensions() -> None:
    assert status_of("F083", page(HOME, doc={"images": [img()]})) == "pass"
    assert status_of("F083", page(HOME, doc={"images": [img(width=None)]})) == "fail"
    assert status_of("F083", page(HOME, doc={"images": [img(height=None)]})) == "fail"
    assert (
        status_of("F083", page(HOME, doc={"images": [img("data:", width=None)]}))
        == "not_applicable"
    )


def test_f084_first_content_image_loading() -> None:
    assert (
        status_of("F084", page(HOME, doc={"images": [img(loading="lazy")]})) == "fail"
    )
    assert (
        status_of("F084", page(HOME, doc={"images": [img(), img(loading="lazy")]}))
        == "pass"
    )
    skipped = [
        img(alt="", decorative=True, loading="lazy"),
        img(in_navigation=True, loading="lazy"),
    ]
    assert status_of("F084", page(HOME, doc={"images": skipped})) == "not_applicable"


# --- media -------------------------------------------------------------------------------------------------


def media(kind: str, **kw: object) -> dict:
    return {"kind": kind, "src": "https://www.example.com/m", **kw}


def test_f087_video_captions() -> None:
    assert (
        status_of(
            "F087", page(HOME, doc={"media": [media("video", has_captions=True)]})
        )
        == "pass"
    )
    bare = page(HOME, doc={"media": [media("video", has_captions=False)]})
    result = run("F087", audit(bare))[0]
    assert result.status == "fail" and result.observed_value == {
        "videos": 1,
        "without_captions": 1,
    }
    embed_only = page(HOME, doc={"media": [media("video_embed")]})
    assert (
        run("F087", audit(embed_only))[0].status == "not_measured"
    )  # cannot see into a player
    assert (
        status_of("F087", page(HOME, doc={"media": [media("audio")]}))
        == "not_applicable"
    )
    assert status_of("F087", page(HOME)) == "not_applicable"


def test_f086_and_f089_transcripts_are_keyword_heuristics() -> None:
    video = {"media": [media("video")]}
    assert run("F086", audit(page(HOME, doc=video)))[0].status == "fail"
    with_heading = {**video, "headings": [Heading(level=2, text="Video transcript")]}
    assert status_of("F086", page(HOME, doc=with_heading)) == "pass"
    with_link = {**video, "anchors": [anchor(text="Read the Transcript")]}
    assert status_of("F086", page(HOME, doc=with_link)) == "pass"
    with_text = {**video, "text": "Full transcript follows below."}
    assert status_of("F086", page(HOME, doc=with_text)) == "pass"
    embed = {"media": [media("video_embed")]}
    assert status_of("F086", page(HOME, doc=embed)) == "fail"
    audio = {"media": [media("audio")]}
    assert status_of("F089", page(HOME, doc=audio)) == "fail"
    assert status_of("F089", page(HOME, doc={**audio, "text": "transcript"})) == "pass"
    assert status_of("F089", page(HOME, doc=video)) == "not_applicable"
    assert run("F089", audit(page(HOME, doc=audio)))[0].is_heuristic


def test_f088_video_metadata() -> None:
    video = {"media": [media("video")]}
    assert status_of("F088", page(HOME, doc=video)) == "fail"  # no VideoObject
    complete = {
        "@type": "VideoObject",
        "name": "n",
        "description": "d",
        "thumbnailUrl": "t",
        "uploadDate": "2026-01-01",
    }
    assert (
        status_of("F088", page(HOME, doc={**video, "structured_data": [complete]}))
        == "pass"
    )
    partial = {"@type": "VideoObject", "name": "n"}
    result = run(
        "F088", audit(page(HOME, doc={**video, "structured_data": [partial]}))
    )[0]
    assert result.status == "fail" and "thumbnailUrl" in result.observed_value[0]
    assert (
        status_of("F088", page(HOME, doc={"structured_data": [complete]}))
        == "not_applicable"
    )


# --- page-type heuristics -----------------------------------------------------------------------------------------


def howto(**kw: object) -> dict:
    return {
        "title": "How to set up billing",
        "headings": [Heading(level=1, text="How to set up billing")],
        **kw,
    }


def test_f094_procedural_steps() -> None:
    ordered = {"lists": [{"kind": "ol", "item_count": 3, "items": ["a", "b", "c"]}]}
    assert status_of("F094", page(HOME, doc=howto(**ordered))) == "pass"
    assert (
        status_of("F094", page(HOME, doc=howto(text="Step 1 Open\nStep 2 Click")))
        == "pass"
    )
    result = run("F094", audit(page(HOME, doc=howto())))[0]
    assert result.status == "fail" and result.is_heuristic
    menu = {"lists": [{"kind": "ol", "item_count": 5, "in_navigation": True}]}
    assert status_of("F094", page(HOME, doc=howto(**menu))) == "fail"
    assert (
        status_of("F094", page(HOME, doc={"title": "Pricing", "headings": []}))
        == "not_applicable"
    )


def test_f095_comparison_structure() -> None:
    page_doc = {
        "title": "Acme vs Globex",
        "headings": [Heading(level=1, text="Acme vs Globex")],
    }
    data_table = {
        "tables": [{"row_count": 3, "column_count": 3, "has_header_cells": True}]
    }
    assert status_of("F095", page(HOME, doc={**page_doc, **data_table})) == "pass"
    assert status_of("F095", page(HOME, doc=page_doc)) == "fail"
    layout = {"tables": [{"row_count": 3, "column_count": 3, "presentational": True}]}
    assert status_of("F095", page(HOME, doc={**page_doc, **layout})) == "fail"
    compare = {"title": "Compare plans", "headings": []}
    assert status_of("F095", page(HOME, doc=compare)) == "fail"
    assert (
        status_of("F095", page(HOME, doc={"title": "About us", "headings": []}))
        == "not_applicable"
    )
