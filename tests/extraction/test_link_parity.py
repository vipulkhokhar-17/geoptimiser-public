"""The crawler and the extractor must agree on what a link is (B2).

If they disagree, the crawler can fetch a page that the extractor's link list never
mentions, and the page then looks orphaned or unreachable although the site links to
it. Both now use the rules in ``geoptimiser.crawler.urls``; this test keeps them tied.
"""

import pytest

from geoptimiser.crawler.urls import extract_links
from geoptimiser.extraction.config import ExtractionConfig
from geoptimiser.extraction.parser import parse_html

BASE = "https://example.com/dir/page"
CASES = {
    "plain": '<a href="/a">a</a><a href="b">b</a>',
    "noscript": '<p>x</p><noscript><a href="/only-in-noscript">n</a></noscript>',
    "noscript_in_head": "<head><noscript><a href='/h'>h</a></noscript></head>",
    "template_is_inert": '<template><a href="/inert">t</a></template><a href="/live">l</a>',
    "svg_is_foreign": '<svg><a href="/svg">s</a></svg><a href="/after-svg">x</a>',
    "base_href": '<head><base href="https://example.com/docs/"></head><a href="guide">g</a>',
    "base_relative": '<head><base href="/docs/"></head><a href="guide">g</a>',
    "base_non_http_ignored": '<head><base href="javascript:x"></head><a href="g">g</a>',
    "second_base_ignored": '<base href="/one/"><base href="/two/"><a href="g">g</a>',
    "fragment_only_skipped": '<a href="#top">t</a><a href="/c#frag">c</a>',
    "non_http_skipped": '<a href="mailto:a@b.c">m</a><a href="javascript:void(0)">j</a><a href="tel:1">t</a>',
    "whitespace_in_href": '<a href=" /sp ace\t\n">x</a><a href="/tab\tbed">y</a>',
    "malformed": '<a href="/m1">m<b>x</a><div><a href=/unquoted>u</a',
    "single_quotes": "<a href='/sq'>s</a>",
    "empty_href": '<a href="">e</a><a>no href</a><a href="   ">w</a>',
    "uppercase_tags": '<A HREF="/UP">u</A>',
    "relative_parent": '<a href="../up">u</a><a href="./same">s</a>',
    "protocol_relative": '<a href="//other.com/x">p</a>',
}


def extractor_links(html: str) -> list[str]:
    page = parse_html(html, BASE, ExtractionConfig())
    return page.links


@pytest.mark.parametrize("name", sorted(CASES))
def test_crawler_and_extractor_find_the_same_links(name: str) -> None:
    html = CASES[name]
    crawler = list(dict.fromkeys(extract_links(html, BASE, limit=500)))
    assert crawler == extractor_links(html), name


def test_noscript_anchor_is_a_link_for_both() -> None:
    html = CASES["noscript"]
    assert "https://example.com/only-in-noscript" in extractor_links(html)
    assert "https://example.com/only-in-noscript" in extract_links(html, BASE, limit=10)


def test_inert_containers_are_not_links_for_either() -> None:
    html = CASES["template_is_inert"]
    assert extractor_links(html) == ["https://example.com/live"]
    assert extract_links(html, BASE, limit=10) == ["https://example.com/live"]


def test_base_href_applies_to_both() -> None:
    for html in (CASES["base_href"], CASES["base_relative"]):
        assert extractor_links(html) == ["https://example.com/docs/guide"]
        assert extract_links(html, BASE, limit=5) == ["https://example.com/docs/guide"]


def test_crawler_limit_still_bounds_the_work() -> None:
    html = "".join(f'<a href="/p{i}">x</a>' for i in range(50))
    assert len(extract_links(html, BASE, limit=7)) == 7
