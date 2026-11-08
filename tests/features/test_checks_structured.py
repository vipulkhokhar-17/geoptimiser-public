"""Categories E and G."""

import pytest

from geoptimiser.features.inputs import PageContext
from tests.features.builders import audit, page, run, status_of, statuses

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
ARTICLE = {
    "@type": "Article",
    "headline": "Guide to pricing",
    "author": {"@type": "Person", "name": "Ada"},
    "datePublished": "2026-01-10",
    "dateModified": "2026-02-01",
}


def sd(*items: dict, **extra: object) -> dict:
    return {
        "structured_data": list(items),
        "structured_data_types": ["Article"],
        **extra,
    }


# --- E: evidence, trust, freshness ---------------------------------------------------------


def test_f041_citation_presence_needs_enough_text() -> None:
    long = "x" * 400
    cited = page(HOME, doc={"text": long, "links": [A, "https://nih.gov/study"]})
    assert run("F041", audit(cited))[0].status == "pass"
    bare = page(HOME, doc={"text": long, "links": [A]})
    result = run("F041", audit(bare))[0]
    assert result.status == "fail" and result.is_heuristic
    assert (
        status_of("F041", page(HOME, doc={"text": "short", "links": []}))
        == "not_applicable"
    )


def test_f046_author_attribution() -> None:
    assert status_of("F046", page(HOME, doc=sd(ARTICLE))) == "pass"
    anonymous = {k: v for k, v in ARTICLE.items() if k != "author"}
    assert status_of("F046", page(HOME, doc=sd(anonymous))) == "fail"
    assert status_of("F046", page(HOME, doc=sd({**ARTICLE, "author": ""}))) == "fail"
    assert (
        status_of("F046", page(HOME, doc=sd({"@type": "Product", "name": "x"})))
        == "not_applicable"
    )
    assert status_of("F046", page(HOME, doc={})) == "not_applicable"
    graph = {"structured_data": [{"@graph": [ARTICLE]}]}
    assert status_of("F046", page(HOME, doc=graph)) == "pass"


def test_f047_publisher_identity() -> None:
    org = {"@type": "Organization", "name": "Acme"}
    assert status_of("F047", page(HOME, doc=sd(org))) == "pass"
    assert (
        status_of(
            "F047", page(HOME, doc=sd({**ARTICLE, "publisher": {"name": "Acme"}}))
        )
        == "pass"
    )
    assert (
        status_of("F047", page(HOME, doc=sd({**ARTICLE, "publisher": "Acme"})))
        == "pass"
    )
    assert status_of("F047", page(HOME, doc=sd(ARTICLE))) == "fail"
    assert status_of("F047", page(HOME, doc={})) == "not_applicable"


def test_f048_and_f049_dates() -> None:
    assert status_of("F048", page(HOME, doc=sd(ARTICLE))) == "pass"
    undated = {k: v for k, v in ARTICLE.items() if not k.startswith("date")}
    assert status_of("F048", page(HOME, doc=sd(undated))) == "fail"
    assert status_of("F048", page(HOME, doc={})) == "not_applicable"
    assert status_of("F049", page(HOME, doc=sd(ARTICLE))) == "pass"
    assert status_of("F049", page(HOME, doc=sd(undated))) == "fail"
    header = {
        "headers": {
            "Content-Type": "text/html",
            "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT",
        }
    }
    assert status_of("F049", page(HOME, doc=sd(undated), fetch=header)) == "pass"


@pytest.mark.parametrize(
    ("published", "modified", "expected"),
    [
        ("2026-01-10", "2026-02-01", "pass"),
        ("2026-02-01", "2026-01-10", "fail"),
        ("2026-01-10T08:00:00Z", "2026-01-10T09:30:00+00:00", "pass"),
        ("yesterday", "2026-01-10", "fail"),
        ("2026-01-10", "2099-01-01", "fail"),
        ("2026-01-10", None, "not_applicable"),
    ],
)
def test_f050_freshness_consistency(
    published: str, modified: str | None, expected: str
) -> None:
    article = {**ARTICLE, "datePublished": published, "dateModified": modified}
    assert status_of("F050", page(HOME, doc=sd(article))) == expected


# --- G: structured data ----------------------------------------------------------------------------


def test_f061_jsonld_validity_distinguishes_none_from_broken() -> None:
    assert (
        status_of("F061", page(HOME, doc={})) == "not_applicable"
    )  # nothing to validate
    assert status_of("F061", page(HOME, doc=sd(ARTICLE))) == "pass"
    broken = page(HOME, doc={"structured_data_errors": 2})
    result = run("F061", audit(broken))[0]
    assert result.status == "fail" and result.observed_value == 2


def test_f062_type_coverage() -> None:
    assert (
        status_of("F062", page(HOME, doc={"structured_data_types": ["Organization"]}))
        == "pass"
    )
    assert status_of("F062", page(HOME, doc={"structured_data_types": []})) == "fail"


def test_f063_generic_property_completeness_excludes_specific_types() -> None:
    complete = sd(
        {"@type": "Organization", "name": "A", "url": "https://a.test", "logo": "l.png"}
    )
    assert status_of("F063", page(HOME, doc=complete)) == "pass"
    thin = sd({"@type": "Organization", "name": "A"})
    result = run("F063", audit(page(HOME, doc=thin)))[0]
    assert result.status == "fail" and "url, logo" in result.observed_value[0]
    assert (
        status_of("F063", page(HOME, doc=sd(ARTICLE))) == "not_applicable"
    )  # F069 covers it
    assert status_of("F063", page(HOME, doc={})) == "not_applicable"


def test_f063_property_policy_is_configuration() -> None:
    thin = sd({"@type": "Organization", "name": "A"})
    relaxed = {"entity_properties": {"Organization": ("name",)}}
    assert status_of("F063", page(HOME, doc=thin), **relaxed) == "pass"


def test_f064_entity_identifiers() -> None:
    with_id = sd({"@type": "Organization", "name": "A", "@id": "https://a.test/#org"})
    assert status_of("F064", page(HOME, doc=with_id)) == "pass"
    same_as = sd({"@type": "Person", "name": "B", "sameAs": ["https://x.test/b"]})
    assert status_of("F064", page(HOME, doc=same_as)) == "pass"
    assert (
        status_of("F064", page(HOME, doc=sd({"@type": "Organization", "name": "A"})))
        == "fail"
    )
    assert status_of("F064", page(HOME, doc=sd(ARTICLE))) == "not_applicable"


def test_f066_organization_consistency_across_pages() -> None:
    def org(name: str) -> dict:
        return sd({"@type": "Organization", "name": name})

    same = audit(page(HOME, doc=org("Acme Inc")), page(A, doc=org("acme  inc")))
    assert run("F066", same)[0].status == "pass"
    differing = audit(
        page(HOME, doc=org("Acme Inc")), page(A, doc=org("Acme Incorporated"))
    )
    result = run("F066", differing)[0]
    assert result.status == "fail" and result.scope == "site"
    assert {e.source_url for e in result.evidence} == {HOME, A}
    assert run("F066", audit(page(HOME, doc=org("Acme"))))[0].status == "not_applicable"


def test_f067_product_and_f068_offer_completeness() -> None:
    product = {
        "@type": "Product",
        "name": "Widget",
        "image": "w.png",
        "description": "d",
        "offers": {"price": "9", "priceCurrency": "EUR", "availability": "InStock"},
    }
    assert status_of("F067", page(HOME, doc=sd(product))) == "pass"
    assert status_of("F068", page(HOME, doc=sd(product))) == "pass"  # nested offers
    partial = {**product, "offers": {"price": "9"}}
    assert status_of("F068", page(HOME, doc=sd(partial))) == "fail"
    no_image = {k: v for k, v in product.items() if k != "image"}
    assert status_of("F067", page(HOME, doc=sd(no_image))) == "fail"
    assert status_of("F067", page(HOME, doc=sd(ARTICLE))) == "not_applicable"
    several = {**product, "offers": [product["offers"], {"price": "1"}]}
    assert status_of("F068", page(HOME, doc=sd(several))) == "fail"


def test_f069_article_completeness() -> None:
    assert status_of("F069", page(HOME, doc=sd(ARTICLE))) == "pass"
    thin = {"@type": "BlogPosting", "headline": "x"}
    result = run("F069", audit(page(HOME, doc=sd(thin))))[0]
    assert result.status == "fail" and "author" in result.observed_value[0]
    assert status_of("F069", page(HOME, doc={})) == "not_applicable"


def test_f070_visible_content_consistency() -> None:
    consistent = {"title": "Guide to pricing", "text": "Guide to pricing\nBody."}
    assert status_of("F070", page(HOME, doc={**sd(ARTICLE), **consistent})) == "pass"
    inconsistent = {"title": "Other", "text": "Nothing relevant.", "headings": []}
    result = run("F070", audit(page(HOME, doc={**sd(ARTICLE), **inconsistent})))[0]
    assert result.status == "fail" and result.is_heuristic
    assert status_of("F070", page(HOME, doc={})) == "not_applicable"


def test_malformed_structured_data_never_breaks_a_check() -> None:
    weird = [
        {"@type": 7, "name": ["a"], "author": None},
        {"@type": ["Article", None, 3], "headline": {"x": 1}, "offers": "free"},
        {"@graph": "not-a-list"},
        {"@graph": [1, "x", {"@type": "Product", "offers": [None, 3, "z"]}]},
        {},
    ]
    inputs = audit(
        page(HOME, doc={"structured_data": weird, "structured_data_types": ["Article"]})
    )
    for fid in (
        "F046",
        "F047",
        "F048",
        "F049",
        "F050",
        "F063",
        "F064",
        "F067",
        "F068",
        "F069",
        "F070",
    ):
        assert run(fid, inputs)[0].status != "error", fid
    assert statuses("F066", inputs)


def _many_products(n: int, visible: str) -> PageContext:
    items = [{"@type": "Product", "name": f"Item {i:04d}"} for i in range(n)]
    return page(HOME, doc={**sd(*items), "title": "Shop", "text": visible})


def test_f070_examines_a_bounded_number_of_values() -> None:
    # Security audit run 1: entities x visible text was unbounded and page-controlled.
    names = " ".join(f"Item {i:04d}" for i in range(300))
    result = run("F070", audit(_many_products(300, names)))[0]
    assert result.status == "not_measured"  # cannot pass on a partial comparison
    assert "200 of 300" in (result.explanation or "")
    missing = run("F070", audit(_many_products(300, "nothing")))[0]
    assert missing.status == "fail" and len(missing.observed_value) == 50
    duplicates = [{"@type": "Product", "name": "Same"} for _ in range(5000)]
    same = page(HOME, doc={**sd(*duplicates), "title": "Same", "text": "Same"})
    assert status_of("F070", same) == "pass"  # distinct values only
