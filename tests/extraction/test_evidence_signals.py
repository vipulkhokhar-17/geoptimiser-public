"""Extractor facts the feature checks rely on to tell a limit from a defect."""

from geoptimiser.extraction.config import ExtractionConfig
from geoptimiser.extraction.parser import parse_html

URL = "https://example.com/"


def parse(html: str, **cfg: int):  # type: ignore[no-untyped-def]
    return parse_html(html, URL, ExtractionConfig(**cfg))


def test_head_is_complete_after_head_end_or_first_body_content() -> None:
    assert parse("<html><head><title>t</title></head><body>x").head_complete
    assert parse("<html><head><title>t</title><p>no explicit head end").head_complete
    assert parse("<title>t</title><body>x").head_complete


def test_head_is_not_complete_when_the_document_ends_inside_it() -> None:
    assert not parse('<html><head><meta charset="utf-8"><title>t</title>').head_complete
    assert not parse("<html><head><script>var x = 1;</script><link rel=a").head_complete


def test_head_content_hidden_in_noscript_does_not_end_the_head() -> None:
    page = parse('<head><noscript><img src="/p.gif"></noscript><title>t</title>')
    assert not page.head_complete


def test_unterminated_title_is_marked_cut() -> None:
    page = parse("<html><head><title>A long title that never")
    assert page.title == "A long title that never" and "title" in page.truncated
    assert "title" not in parse("<title>Closed</title>").truncated


def test_json_ld_causes_are_recorded_per_block() -> None:
    ok = '<script type="application/ld+json">{"@type":"Thing"}</script>'
    bad = '<script type="application/ld+json">{"@type": }</script>'
    page = parse(ok + bad + bad)
    assert page.structured_data_errors == 2
    assert page.structured_data_error_causes == {"syntax_error": 2}
    assert len(page.structured_data) == 1


def test_unclosed_json_ld_is_recorded_as_unterminated_not_syntax() -> None:
    page = parse('<script type="application/ld+json">{"@type":"Thing","name":"cut')
    assert page.structured_data_error_causes == {"unterminated": 1}


def test_oversized_json_ld_is_a_size_limit_not_a_syntax_error() -> None:
    big = '<script type="application/ld+json">{"a":"%s"}</script>' % ("x" * 500)
    page = parse(big, max_json_ld_bytes=100)
    assert page.structured_data_error_causes == {"size_limit": 1}
    assert "structured_data" in page.truncated


def test_deeply_nested_json_ld_is_a_nesting_limit() -> None:
    nested = "[" * 1_100 + "]" * 1_100
    page = parse(f'<script type="application/ld+json">{nested}</script>')
    assert page.structured_data_error_causes == {"nesting_limit": 1}


def test_render_signals_describe_the_initial_html() -> None:
    html = (
        '<html><body><div id="root"></div>'
        "<noscript>You need to enable JavaScript to run this app.</noscript>"
        '<script src="/a.js"></script><script>var big = 1;</script></body></html>'
    )
    page = parse(html)
    assert page.script_tags == 2 and page.external_scripts == 1
    assert page.mount_points == ["#root"]
    assert page.noscript_notice and "enable JavaScript" in page.noscript_notice
    assert page.inline_script_chars == len("var big = 1;")


def test_plain_server_rendered_page_has_no_shell_signals() -> None:
    page = parse("<html><body><h1>Hi</h1><p>Text.</p></body></html>")
    assert page.script_tags == 0 and not page.mount_points and not page.noscript_notice
