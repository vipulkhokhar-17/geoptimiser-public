import pytest
from pydantic import ValidationError

from geoptimiser.schemas import Citation, VisibilityObservation
from geoptimiser.visibility.annotate import (
    BrandSpec,
    Entity,
    annotate,
    cited_urls,
    mentions,
)

ACME = Entity(name="Acme", aliases=("Acme Cloud",), domains=("Acme.com",))
SPEC = BrandSpec(
    brand=ACME, competitors=(Entity(name="Globex", domains=("globex.io",)),)
)


def obs(text: str = "", status: str = "success", cites: tuple[str, ...] = ()):
    extra = {} if status == "success" else {"error_message": "boom"}
    if status == "skipped":
        extra = {"error_message": "no credentials"}
    return VisibilityObservation(
        audit_id="a1",
        query_id="q1",
        query_set_version=1,
        provider="p",
        model="m",
        query="what is x",
        response_text=text if status == "success" else "",
        citations=tuple(Citation(url=u) for u in cites),
        collection_status=status,
        **extra,
    )


def test_whole_word_case_insensitive():
    assert mentions("I like ACME a lot", ACME)
    assert not mentions("Welcome to Acmeville", ACME)
    assert not mentions("preacme", ACME)


def test_alias_and_domain_match():
    assert mentions("try Acme Cloud today", ACME)
    assert mentions("see acme.com for details", ACME)


def test_regex_metacharacters_are_literal():
    e = Entity(name="C++ Co")
    assert mentions("we use C++ Co daily", e)
    assert not mentions("we use CXX Co daily", e)


def test_domain_is_normalised():
    assert ACME.domains == ("acme.com",)


def test_short_or_duplicate_names_rejected():
    with pytest.raises(ValidationError):
        Entity(name="A")
    with pytest.raises(ValidationError):
        Entity(name="Acme", aliases=("x",))
    with pytest.raises(ValidationError):
        BrandSpec(brand=ACME, competitors=(Entity(name="acme"),))


def test_annotate_sets_brand_and_competitors():
    out = annotate(obs("Acme beats Globex"), SPEC)
    assert out.brand_mentioned is True
    assert out.competitors_mentioned == ("Globex",)
    assert annotate(obs("nothing here"), SPEC).brand_mentioned is False


def test_annotate_leaves_failures_unmeasured():
    for status in ("error", "skipped"):
        out = annotate(obs(status=status), SPEC)
        assert out.brand_mentioned is None
        assert out.competitors_mentioned == ()


def test_annotate_is_idempotent_and_pure():
    original = obs("Acme")
    once = annotate(original, SPEC)
    assert original.brand_mentioned is None
    assert annotate(once, SPEC) == once


def test_cited_urls_match_domain_and_subdomains_only():
    o = obs(
        "x",
        cites=(
            "https://acme.com/a#frag",
            "https://docs.acme.com/b",
            "https://notacme.com/c",
            "https://acme.com.evil.net/d",
            "https://globex.io/e",
        ),
    )
    assert cited_urls(o, ACME) == ["https://acme.com/a", "https://docs.acme.com/b"]
