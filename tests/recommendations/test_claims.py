import pytest

from geoptimiser.features.registry import default_registry
from geoptimiser.recommendations import claim_problems, ungrounded_urls
from geoptimiser.recommendations.claims import authored_text


@pytest.mark.parametrize(
    "text",
    [
        "This will increase AI citations by 40%.",
        "Expect 3x more visibility",
        "Triple your traffic",
        "We guarantee a top ranking",
        "Guaranteed results",
        "You will rank #1 for this query",
        "It will definitely improve your visibility",
        "Land on the first page of answers",
        "a 2.5 times lift",
        "an increase of 12 percent",
    ],
)
def test_unsupported_claims_are_flagged(text):
    assert claim_problems(text)


@pytest.mark.parametrize(
    "text",
    [
        "Add a unique, descriptive <title>.",
        "Keep the title under 60 characters.",
        "Re-run F021 after the change; the affected URLs should report pass.",
        "This may help engines understand the page.",
        "Use at most 3 headings per section.",
    ],
)
def test_ordinary_guidance_is_not_flagged(text):
    assert claim_problems(text) == []


def test_every_catalog_remediation_is_clean():
    for defn in default_registry().catalog.features:
        assert claim_problems(defn.remediation or "") == [], defn.feature_id


def test_ungrounded_urls():
    text = "See https://a.test/x and https://evil.test/y."
    assert ungrounded_urls(text, ["https://a.test/x"]) == ["https://evil.test/y"]
    assert ungrounded_urls("no urls", []) == []
    assert ungrounded_urls("https://a.test/x/", ["https://a.test/x"]) == []


# Security audit run 1: site-controlled text (URLs, quoted page excerpts) reached the
# unsupported-claim screen, so a crawled URL like ".../50%25-off" suppressed a valid
# recommendation. Only Geoptimiser's own prose is screened now.
def test_crawled_urls_and_quotes_do_not_trigger_the_claim_screen():
    text = (
        "Add a <title> to https://shop.test/sale/50%25-off. The page heading reads "
        '"Triple your traffic with 3x deals".'
    )
    assert claim_problems(text)  # the raw text would be rejected
    assert claim_problems(authored_text(text)) == []


def test_authored_claims_are_still_flagged_next_to_urls():
    text = "This will increase AI citations by 40% at https://shop.test/a."
    assert claim_problems(authored_text(text))
