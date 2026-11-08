"""Rich extraction: images, anchors, landmarks, tables, lists, media, viewport."""

import time
from collections.abc import Callable

import pytest

from geoptimiser.extraction.config import ExtractionConfig
from geoptimiser.extraction.parser import ParsedPage, parse_html

PAGE = "https://www.example.com/p"
Read = Callable[[str], str]


def parse(html: str, url: str = PAGE, **limits: object) -> ParsedPage:
    return parse_html(html, url, ExtractionConfig(**limits))  # type: ignore[arg-type]


# --- the full fixture -------------------------------------------------------------------


def test_head_signals(fixture_html: Read) -> None:
    page = parse(fixture_html("rich_page"))
    assert page.viewport == "width=device-width, initial-scale=1"
    assert page.charset_declared == "utf-8"


def test_images_keep_attributes_and_context(fixture_html: Read) -> None:
    images = parse(fixture_html("rich_page")).images
    assert [i["src"] for i in images] == [
        "https://www.example.com/img/team-photo.jpg",
        "https://cdn.example.org/chart.png",
        "https://www.example.com/img/spacer.gif",
        "data:",  # inline data URIs are not stored
        "https://www.example.com/img/logo.png",
    ]  # the <noscript> tracking pixel is not collected
    team, chart, spacer, inline, logo = images
    assert (team["alt"], team["width"], team["height"], team["loading"]) == (
        "Our team",
        640,
        480,
        "lazy",
    )
    assert "Intro text before the picture." in team["context_before"]
    assert team["context_after"].startswith("Text after the picture continues here.")
    assert (
        chart["alt"] is None and chart["decorative"] is False
    )  # alt absent, not decorative
    assert chart["caption"] == "Revenue chart"
    assert (
        spacer["alt"] == "" and spacer["decorative"] is True
    )  # empty alt + role=presentation
    assert inline["alt"] == "inline"
    assert logo["alt"] == "Company logo"


def test_anchors_have_text_rel_region_and_classification(fixture_html: Read) -> None:
    anchors = parse(fixture_html("rich_page")).anchors
    by_text = {a["text"]: a for a in anchors}
    assert list(by_text) == [
        "Home",
        "Pricing",
        "Docs",
        "Blog",
        "the study",
        "click here",
        "Company logo",
        "Privacy",
    ]
    assert by_text["Pricing"]["rel"] == ("nofollow",)
    assert by_text["the study"]["rel"] == ("noopener", "ugc")
    assert (
        by_text["the study"]["internal"] is False
        and by_text["Home"]["internal"] is True
    )
    assert (
        by_text["Home"]["region"] == "navigation"
        and by_text["click here"]["region"] == "content"
    )
    assert by_text["Privacy"]["region"] == "navigation"  # footer
    logo = by_text["Company logo"]  # no text: the image alt names the link
    assert logo["has_image"] is True and logo["href"] == "https://www.example.com/logo"


def test_landmarks_and_region_text(fixture_html: Read) -> None:
    page = parse(fixture_html("rich_page"))
    kinds = [(m["kind"], m["source"], m["labelled"]) for m in page.landmarks]
    assert kinds == [
        ("banner", "tag", False),
        ("navigation", "tag", True),
        ("main", "tag", False),
        ("complementary", "role", True),
        ("contentinfo", "tag", False),
    ]
    assert (
        next(m for m in page.landmarks if m["kind"] == "navigation")["label"]
        == "Primary"
    )
    assert page.semantic_counts["main"] == 1 and page.semantic_counts["figure"] == 1
    assert page.boilerplate_chars == 45 and page.main_chars > 100
    assert page.hidden_chars == len("Secret hidden words that are not shown.")
    assert "Secret hidden" not in page.text


def test_tables_lists_and_media(fixture_html: Read) -> None:
    page = parse(fixture_html("rich_page"))
    (table,) = page.tables
    assert table["caption"] == "Plans" and table["header_cells"] == ("Plan", "Price")
    assert (
        table["row_count"] == 3
        and table["column_count"] == 2
        and table["has_header_cells"]
    )
    assert table["rows"][1] == ("Free", "$0")
    kinds = [(b["kind"], b["item_count"], b["in_navigation"]) for b in page.lists]
    assert kinds == [("ul", 2, True), ("ol", 2, False), ("dl", 1, False)]
    assert page.lists[1]["items"] == ("First step", "Second step")
    assert [(m["kind"], m["has_captions"]) for m in page.media] == [
        ("video", True), ("audio", None), ("video_embed", None),
    ]  # fmt: skip
    assert page.media[0]["src"] == "https://www.example.com/media/intro.mp4"
    assert all("ads.example.net" not in (m["src"] or "") for m in page.media)


def test_rich_extraction_does_not_change_the_existing_fields(
    fixture_html: Read,
) -> None:
    page = parse(fixture_html("rich_page"))
    assert page.title == "Rich page" and page.language == "en"
    assert page.headings == [(1, "Rich page")]
    assert "https://www.example.com/pricing" in page.links
    assert "javascript" not in " ".join(page.links)


# --- empty, incomplete and malformed ----------------------------------------------------------


@pytest.mark.parametrize("name", ["empty", "blank"])
def test_empty_documents_have_no_rich_content(fixture_html: Read, name: str) -> None:
    page = parse(fixture_html(name))
    assert page == ParsedPage(head_complete=name == "empty")


def test_incomplete_fragment(fixture_html: Read) -> None:
    page = parse(fixture_html("rich_incomplete"), "https://www.example.com/dir/x")
    assert (
        page.viewport is None and page.charset_declared is None and page.landmarks == []
    )
    (image,) = page.images
    assert image["src"] == "https://www.example.com/dir/a.png" and image["alt"] is None
    assert image["context_after"].startswith("Fragment with a relative link")
    assert page.anchors[0]["href"] == "https://www.example.com/dir/page"
    assert page.boilerplate_chars == 0 and page.main_chars == 0


def test_malformed_markup_is_read_tolerantly(fixture_html: Read) -> None:
    page = parse(fixture_html("rich_malformed"), "https://www.example.com/m/")
    srcs = [i["src"] for i in page.images]
    assert srcs == [
        None,
        "https://www.example.com/spaces.png",
        "https://www.example.com/f.png",
    ]
    no_src, spaces, figure = page.images
    assert no_src["alt"] == "No source"
    assert (
        spaces["width"] is None
        and spaces["height"] == 12
        and spaces["loading"] == "eager"
    )
    assert figure["caption"].startswith(
        "Never closed"
    )  # an unclosed figcaption still closes
    assert [a["text"] for a in page.anchors] == ["First", "Second"]  # nested <a> split
    (table,) = page.tables  # unclosed rows and cells, stray </table>
    assert (
        table["row_count"] == 2
        and table["column_count"] == 2
        and not table["has_header_cells"]
    )
    assert table["rows"][0] == ("Unclosed cell", "Second cell")
    assert [b["kind"] for b in page.lists] == ["ul"]  # the stray <li> is not a list
    assert page.lists[0]["items"] == ("Alpha", "Beta")
    assert [(m["kind"], m["has_captions"]) for m in page.media] == [("video", False)]
    assert [m["kind"] for m in page.landmarks].count("main") == 2
    assert [m["labelled"] for m in page.landmarks if m["kind"] == "navigation"] == [
        False,
        False,
    ]


# --- what is skipped ------------------------------------------------------------------------------


def test_hidden_inert_and_foreign_elements_are_not_collected() -> None:
    page = parse(
        '<div hidden><img src="/a.png" alt="x"><a href="/h">hidden link</a><table><tr><td>h</td></tr></table></div>'
        '<div style="display:none"><ul><li>hidden item</li></ul><video src="/v.mp4"></video></div>'
        '<template><img src="/t.png"><a href="/t">t</a></template>'
        '<svg><image href="/s.png"/><a href="/svg">svg link</a></svg>'
        '<noscript><img src="/n.png"><a href="/n">n</a></noscript>'
        '<p>visible <img src="/ok.png" alt="ok"></p>'
    )
    assert [i["src"] for i in page.images] == ["https://www.example.com/ok.png"]
    assert (
        page.anchors == []
        and page.tables == []
        and page.lists == []
        and page.media == []
    )
    assert page.hidden_chars > 0


def test_non_http_and_empty_anchors_are_not_collected() -> None:
    page = parse(
        '<a href="mailto:a@b.c">m</a><a href="javascript:void(0)">j</a><a href="#top">t</a>'
        '<a href="">e</a><a href="  ">s</a><a name="x">n</a><a href="/ok">ok</a>'
    )
    assert [a["text"] for a in page.anchors] == ["ok"]


def test_duplicate_anchors_are_collapsed_but_different_text_is_kept() -> None:
    page = parse('<a href="/x">One</a><a href="/x">One</a><a href="/x">Two</a>')
    assert [a["text"] for a in page.anchors] == ["One", "Two"]


def test_base_href_applies_to_anchors_and_images() -> None:
    page = parse(
        '<base href="https://cdn.test/root/"><a href="x">x</a><img src="i.png" alt="i">'
    )
    assert page.anchors[0]["href"] == "https://cdn.test/root/x"
    assert page.images[0]["src"] == "https://cdn.test/root/i.png"
    assert page.anchors[0]["internal"] is False  # relative to the page's own host


def test_subdomains_count_as_internal() -> None:
    page = parse(
        '<a href="https://docs.example.com/a">d</a><a href="https://example.com/b">b</a><a href="https://example.org/">o</a>'
    )
    assert [a["internal"] for a in page.anchors] == [True, True, False]


def test_landmark_roles_and_labelled_sections() -> None:
    page = parse(
        '<div role="main">m</div><div role="navigation">n</div><section aria-label="Pricing">p</section>'
        '<section>unlabelled</section><div role="region">r</div><div role="search">s</div>'
    )
    assert [(m["kind"], m["source"]) for m in page.landmarks] == [
        ("main", "role"), ("navigation", "role"), ("region", "tag"), ("search", "role"),
    ]  # fmt: skip


def test_header_and_footer_inside_an_article_are_not_page_boilerplate() -> None:
    page = parse(
        "<article><header>Article title</header><p>Body</p><footer>by me</footer></article>"
    )
    assert [m["kind"] for m in page.landmarks] == ["article"]
    assert page.boilerplate_chars == 0 and page.main_chars > 0


def test_viewport_and_charset_variants() -> None:
    page = parse(
        '<meta http-equiv="Content-Type" content="text/html; charset=ISO-8859-1"><meta name="Viewport" content=" width=500 ">'
    )
    assert page.charset_declared == "iso-8859-1" and page.viewport == "width=500"
    first = parse(
        '<meta charset="utf-8"><meta charset="latin1"><meta name="viewport" content="a"><meta name="viewport" content="b">'
    )
    assert first.charset_declared == "utf-8" and first.viewport == "a"
    assert parse('<meta charset="">').charset_declared is None
    assert parse('<meta name="viewport">').viewport is None


def test_presentational_tables_and_stray_cells() -> None:
    page = parse(
        '<table role="presentation"><tr><td>layout</td></tr></table><td>stray</td><tr><td>x</td></tr>'
    )
    assert len(page.tables) == 1 and page.tables[0]["presentational"] is True


def test_nested_lists_and_tables_are_separate() -> None:
    page = parse(
        "<ul><li>A<ul><li>B</li></ul></li></ul><table><tr><td>o<table><tr><td>i</td></tr></table></td></tr></table>"
    )
    assert sorted((b["depth"], b["items"]) for b in page.lists) == [
        (0, ("A",)),
        (1, ("B",)),
    ]
    assert len(page.tables) == 2


# --- bounds --------------------------------------------------------------------------------------------


def many(fmt: str, n: int) -> str:
    return "".join(fmt.format(i=i) for i in range(n))


def test_each_collection_is_bounded_and_flags_its_cut() -> None:
    cases = [
        (many('<img src="/{i}.png" alt="a">', 6), {"max_images": 2}, "images", lambda p: len(p.images) == 2),
        (many('<a href="/{i}">t{i}</a>', 6), {"max_anchors": 3}, "anchors", lambda p: len(p.anchors) == 3),
        (many("<nav>n</nav>", 6), {"max_landmarks": 2}, "landmarks", lambda p: len(p.landmarks) == 2),
        (many("<table><tr><td>x</td></tr></table>", 4), {"max_tables": 1}, "tables", lambda p: len(p.tables) == 1),
        (many("<ul><li>x</li></ul>", 4), {"max_lists": 1}, "lists", lambda p: len(p.lists) == 1),
        (many('<video src="/{i}.mp4"></video>', 4), {"max_media": 2}, "media", lambda p: len(p.media) == 2),
    ]  # fmt: skip
    for html, limits, flag, ok in cases:
        page = parse(html, **limits)
        assert ok(page), flag
        assert flag in page.truncated, flag


def test_table_rows_and_cells_are_bounded_but_counts_are_exact() -> None:
    rows = many("<tr><td>a</td><td>b</td><td>c</td></tr>", 10)
    page = parse(f"<table>{rows}</table>", max_table_rows=3, max_table_cells=2)
    (table,) = page.tables
    assert table["row_count"] == 10 and table["column_count"] == 3
    assert len(table["rows"]) == 3 and all(len(r) == 2 for r in table["rows"])
    assert "tables" in page.truncated


def test_list_items_are_bounded_but_the_count_is_exact() -> None:
    page = parse("<ol>" + many("<li>item {i}</li>", 8) + "</ol>", max_list_items=3)
    (block,) = page.lists
    assert block["item_count"] == 8 and len(block["items"]) == 3
    assert "lists" in page.truncated


def test_text_fields_are_clipped() -> None:
    page = parse(
        '<a href="/x">'
        + "word " * 200
        + "</a><table><tr><td>"
        + "x" * 500
        + "</td></tr></table>",
        max_anchor_chars=20,
        max_cell_chars=30,
    )
    assert len(page.anchors[0]["text"]) <= 20
    assert len(page.tables[0]["rows"][0][0]) <= 30


def test_image_context_is_bounded() -> None:
    page = parse(
        "<p>" + "before " * 100 + '<img src="/i.png"> ' + "after " * 100 + "</p>",
        context_chars=40,
    )
    (image,) = page.images
    assert len(image["context_before"]) <= 40 and len(image["context_after"]) <= 40
    assert image["context_before"].endswith("before") and image[
        "context_after"
    ].startswith("after")


def test_overlong_urls_are_dropped_not_stored() -> None:
    page = parse(f'<img src="/{"a" * 600}.png" alt="x"><a href="/{"b" * 3000}">t</a>')
    assert page.images[0]["src"] is None and page.anchors == []


def test_pathological_nesting_does_not_break_the_collectors() -> None:
    html = (
        "<div>" * 1000
        + "<nav><a href='/x'>x</a></nav>"
        + "<table><tr><td>t</td></tr></table>"
        + "</div>" * 1000
    )
    page = parse(html, max_nesting_depth=64)
    assert isinstance(
        page.anchors, list
    )  # past the cap elements are not tracked, nothing raises


def test_thousands_of_elements_stay_fast() -> None:
    html = many(
        '<p><a href="/{i}">link {i}</a><img src="/{i}.png" alt="i{i}"></p>', 3000
    )
    started = time.monotonic()
    page = parse(html, max_anchors=500, max_images=500)
    assert time.monotonic() - started < 5
    assert len(page.anchors) == 500 and len(page.images) == 500


def test_counters_recover_after_unbalanced_markup() -> None:
    page = parse("</nav></main></article><nav>a</nav><p>after</p><main>b</main>")
    assert (
        page.boilerplate_chars == 1 and page.main_chars == 1
    )  # no negative/stuck counters
