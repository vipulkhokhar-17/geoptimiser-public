import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from geoptimiser.features import CATALOG, FeatureConfig
from geoptimiser.features.catalog import (
    AVAILABLE_INPUTS,
    FeatureCatalog,
    FeatureDefinition,
)
from geoptimiser.features.export import catalog_json, catalog_markdown, scoring_json

ROOT = Path(__file__).resolve().parents[2]

REQUIRED = {
    "F001": "HTTP success status",
    "F002": "Crawlable page links",
    "F003": "Robots.txt accessibility",
    "F004": "Robots policy compliance",
    "F005": "Meta robots directives",
    "F006": "X-Robots-Tag directives",
    "F007": "Sitemap availability",
    "F008": "Sitemap URL coverage",
    "F009": "Orphan-page risk",
    "F010": "Crawl depth",
    "F011": "Canonical tag presence",
    "F012": "Canonical target validity",
    "F013": "Canonical consistency",
    "F014": "Duplicate page content",
    "F015": "Redirect-chain length",
    "F016": "Redirect-loop detection",
    "F017": "Broken internal links",
    "F018": "URL parameter proliferation",
    "F019": "URL semantic readability",
    "F020": "HTTPS consistency",
    "F021": "Title presence",
    "F022": "Title uniqueness",
    "F023": "Title descriptiveness",
    "F024": "Meta-description presence",
    "F025": "Meta-description uniqueness",
    "F026": "Description-content alignment",
    "F027": "Language declaration",
    "F028": "Character encoding declaration",
    "F029": "Viewport configuration",
    "F030": "Search snippet restrictions",
    "F031": "Main-topic clarity",
    "F032": "Search-intent coverage",
    "F033": "Direct-answer availability",
    "F034": "Key-information prominence",
    "F035": "Heading hierarchy",
    "F036": "Section descriptiveness",
    "F037": "Topical completeness",
    "F038": "Entity coverage",
    "F039": "Terminology consistency",
    "F040": "Question-and-answer coverage",
    "F041": "Source citation presence",
    "F042": "Citation-target validity",
    "F043": "Claim-evidence proximity",
    "F044": "Quantitative evidence",
    "F045": "Methodology transparency",
    "F046": "Author attribution",
    "F047": "Publisher identity",
    "F048": "Publication-date availability",
    "F049": "Modification-date availability",
    "F050": "Freshness consistency",
    "F051": "Extractable main text",
    "F052": "Main-content signal",
    "F053": "Navigation-to-content ratio",
    "F054": "Hidden-content proportion",
    "F055": "Semantic HTML usage",
    "F056": "Table structure",
    "F057": "List structure",
    "F058": "Descriptive anchor text",
    "F059": "Heading and landmark accessibility",
    "F060": "Text-to-markup ratio",
    "F061": "JSON-LD validity",
    "F062": "Structured-data type coverage",
    "F063": "Structured-data property completeness",
    "F064": "Entity identifier availability",
    "F065": "Entity relationship coverage",
    "F066": "Organization consistency",
    "F067": "Product entity completeness",
    "F068": "Offer and pricing completeness",
    "F069": "Article metadata completeness",
    "F070": "Visible-content consistency",
    "F071": "Internal-link density",
    "F072": "Incoming-link count",
    "F073": "Outgoing-link count",
    "F074": "Hub-page identification",
    "F075": "Topic-cluster connectivity",
    "F076": "Important-page accessibility",
    "F077": "Contextual-link coverage",
    "F078": "Anchor-target relevance",
    "F079": "Broken-link concentration",
    "F080": "Cross-page topic redundancy",
    "F081": "Image alternative text",
    "F082": "Image filename descriptiveness",
    "F083": "Image dimension availability",
    "F084": "Image loading behavior",
    "F085": "Image context alignment",
    "F086": "Video transcript availability",
    "F087": "Video caption availability",
    "F088": "Video metadata completeness",
    "F089": "Audio transcript availability",
    "F090": "Multimodal content dependence",
    "F091": "Chunkable section structure",
    "F092": "Section self-containment",
    "F093": "Definition availability",
    "F094": "Procedural-step clarity",
    "F095": "Comparison structure",
    "F096": "Fact extractability",
    "F097": "Answer-context proximity",
    "F098": "Entity disambiguation",
    "F099": "Source-boundary clarity",
    "F100": "Retrieval-query coverage",
    "F101": "Response latency",
    "F102": "Response-size efficiency",
    "F103": "Compression support",
    "F104": "Cache-header configuration",
    "F105": "ETag and Last-Modified availability",
    "F106": "Mobile viewport support",
    "F107": "Core Web Vitals",
    "F108": "JavaScript content dependence",
    "F109": "Resource failure signals",
    "F110": "Security transport configuration",
    "F111": "AI-answer mention rate",
    "F112": "Citation frequency",
    "F113": "Unique cited-page coverage",
    "F114": "Citation prominence",
    "F115": "Answer factual coverage",
    "F116": "Citation-to-claim support",
    "F117": "Citation absorption",
    "F118": "Cross-run consistency",
    "F119": "Query coverage",
    "F120": "Before/after visibility change",
}


def test_required_catalog_has_120_entries() -> None:
    assert len(REQUIRED) == 120


def test_every_required_id_exists_exactly_once_with_its_stable_name() -> None:
    counts = Counter(f.feature_id for f in CATALOG.features)
    assert set(counts) == set(REQUIRED)
    assert all(n == 1 for n in counts.values())
    for feature in CATALOG.features:
        assert feature.name == REQUIRED[feature.feature_id], feature.feature_id


def test_twelve_categories_with_ten_features_each() -> None:
    assert [c.code for c in CATALOG.categories] == list("ABCDEFGHIJKL")
    for category in CATALOG.categories:
        ids = [f.feature_id for f in CATALOG.by_category(category.code)]
        assert len(ids) == 10, category.code
    assert CATALOG.by_category("A")[0].feature_id == "F001"
    assert CATALOG.by_category("L")[-1].feature_id == "F120"


def test_ids_follow_category_blocks() -> None:
    for feature in CATALOG.features:
        assert (
            feature.category == "ABCDEFGHIJKL"[(int(feature.feature_id[1:]) - 1) // 10]
        )


def test_lookup() -> None:
    assert CATALOG.get("F021").name == "Title presence"
    with pytest.raises(KeyError):
        CATALOG.get("F999")
    assert {f.feature_id for f in CATALOG.by_status("unavailable")} == {"F085", "F107"}


def test_every_entry_has_the_required_metadata() -> None:
    for f in CATALOG.features:
        for text in (
            f.description,
            f.rationale,
            f.measurement,
            f.output_type,
            f.applicability,
            f.method,
            f.evidence_requirements,
            f.severity_policy,
            f.scoring_policy,
            f.test_requirements,
        ):
            assert text.strip(), f.feature_id
        assert f.limitations and f.inputs
        assert f.implementation_status in (
            "implemented",
            "partial",
            "planned",
            "unavailable",
        )


def test_status_and_measurability_are_consistent() -> None:
    for f in CATALOG.features:
        runnable = f.implementation_status in ("implemented", "partial")
        assert f.measurable_now is runnable, f.feature_id
        if runnable:
            assert f.check_version >= 1 and not f.blocked_by
            assert set(f.inputs) <= AVAILABLE_INPUTS, f.feature_id
        else:
            assert f.check_version == 0 and f.blocked_by, f.feature_id
            assert "Not yet measured" in f.scoring_policy


def test_heuristic_and_partial_entries_state_limitations() -> None:
    for f in CATALOG.features:
        if f.implementation_status == "partial" or f.is_heuristic:
            assert any(x != "None beyond the stated method." for x in f.limitations), (
                f.feature_id
            )


def test_unscored_features_say_why() -> None:
    for f in CATALOG.features:
        if not f.scored and f.measurable_now:
            assert "Unscored" in f.scoring_policy and len(f.scoring_policy) > 60


def test_overlapping_features_document_their_distinction() -> None:
    pairs = {(f.feature_id, o.feature_id) for f in CATALOG.features for o in f.overlaps}
    for a, b in [
        ("F002", "F071"),
        ("F014", "F022"),
        ("F029", "F106"),
        ("F017", "F079"),
    ]:
        assert (a, b) in pairs or (b, a) in pairs
    for f in CATALOG.features:
        for o in f.overlaps:
            assert o.feature_id != f.feature_id and len(o.distinction) >= 10


def test_config_keys_exist_in_the_feature_config() -> None:
    fields = set(FeatureConfig.model_fields)
    for f in CATALOG.features:
        assert set(f.config_keys) <= fields, f.feature_id


def test_the_four_pillars_are_all_represented() -> None:
    assert {f.pillar for f in CATALOG.features} == {
        "technical_health",
        "content_quality",
        "retrieval_readiness",
        "ai_visibility",
    }
    assert {f.pillar for f in CATALOG.by_category("L")} == {"ai_visibility"}
    assert {f.pillar for f in CATALOG.by_category("J")} == {"retrieval_readiness"}


def test_ai_visibility_features_are_not_implemented() -> None:
    assert all(not f.measurable_now for f in CATALOG.by_category("L"))


def test_catalog_validation_rejects_bad_catalogs() -> None:
    first = CATALOG.features[0]
    with pytest.raises(ValidationError, match="duplicate"):
        FeatureCatalog(
            version=1, categories=CATALOG.categories, features=(first, first)
        )
    broken = first.model_dump() | {"implementation_status": "planned"}
    with pytest.raises(ValidationError):  # planned but measurable_now and no blocker
        FeatureDefinition.model_validate(broken)
    liar = first.model_dump() | {"inputs": ("ai_provider",)}
    with pytest.raises(ValidationError, match="unavailable inputs"):
        FeatureDefinition.model_validate(liar)
    with pytest.raises(ValidationError, match="bad overlap"):
        bad = first.model_dump() | {
            "overlaps": ({"feature_id": "F999", "distinction": "x" * 20},)
        }
        FeatureCatalog(
            version=1,
            categories=CATALOG.categories,
            features=(FeatureDefinition.model_validate(bad), *CATALOG.features[1:]),
        )


def test_checked_in_exports_match_the_catalog() -> None:
    assert (ROOT / "configs" / "feature_catalog.json").read_text() == catalog_json()
    assert (ROOT / "configs" / "scoring.json").read_text() == scoring_json()
    assert (ROOT / "docs" / "FEATURE_CATALOG.md").read_text() == catalog_markdown()


def test_json_catalog_round_trips() -> None:
    data = json.loads(catalog_json())
    assert data["version"] == CATALOG.version
    assert FeatureCatalog.model_validate(data) == CATALOG


def test_catalog_text_makes_no_unsupported_outcome_claims() -> None:
    """Rationale, descriptions and remediation may say what a signal is for, never
    that fixing it improves rankings, authority or citations (docs/validation)."""
    import re

    banned = re.compile(
        r"\b(guarantee[sd]?|will (?:improve|increase|boost|rank|be cited)|"
        r"rarely cited|more authority|carry less|boosts?|ranking factor)\b",
        re.I,
    )
    hits = [
        (f.feature_id, field)
        for f in CATALOG.features
        for field in ("description", "rationale", "remediation")
        if banned.search(getattr(f, field) or "")
    ]
    assert not hits, hits
