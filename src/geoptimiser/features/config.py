"""Explicit, versioned thresholds and word lists for the feature checks.

Every number and list here is a *policy default*: a configurable starting point,
not a universal ranking factor and not a claim about how any search system works.
Checks read thresholds only from this object, never from constants in their code.
"""

from pydantic import BaseModel, ConfigDict, Field

_ARTICLE_TYPES = (
    "Article",
    "NewsArticle",
    "BlogPosting",
    "TechArticle",
    "ScholarlyArticle",
)


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # A: crawlability and discovery
    min_crawlable_links: int = Field(default=1, ge=0)
    max_click_depth: int = Field(default=3, ge=0)
    audit_agent_tokens: tuple[str, ...] = ("GeoptimiserBot",)
    # Common AI-crawler user-agent tokens; verify against each vendor's documentation.
    ai_crawler_tokens: tuple[str, ...] = (
        "GPTBot",
        "OAI-SearchBot",
        "ChatGPT-User",
        "ClaudeBot",
        "PerplexityBot",
        "Google-Extended",
        "CCBot",
    )
    # B: URLs
    max_redirect_hops: int = Field(default=1, ge=0)
    max_query_parameters: int = Field(default=3, ge=0)
    duplicate_min_text_chars: int = Field(default=100, ge=1)
    max_url_segment_chars: int = Field(default=60, ge=1)
    # C: metadata
    generic_titles: tuple[str, ...] = (
        "home",
        "homepage",
        "index",
        "untitled",
        "welcome",
        "new page",
        "page",
        "default",
    )
    description_term_coverage_min: float = Field(default=0.5, ge=0, le=1)
    # D: content
    h1_overlap_min: float = Field(default=0.5, ge=0, le=1)
    generic_headings: tuple[str, ...] = (
        "heading",
        "untitled",
        "section",
        "more",
        "click here",
        "read more",
        "learn more",
    )
    # E: trust
    min_text_chars_for_citation_check: int = Field(default=300, ge=1)
    article_types: tuple[str, ...] = _ARTICLE_TYPES
    # F: extraction
    min_extractable_chars: int = Field(default=100, ge=1)
    min_text_to_markup_ratio: float = Field(default=0.02, ge=0, le=1)
    # G: structured data (project policy, not schema.org or Google requirements)
    entity_properties: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: {
            **{
                t: ("headline", "author", "datePublished", "dateModified")
                for t in _ARTICLE_TYPES
            },
            "Product": ("name", "image", "description", "offers"),
            "Offer": ("price", "priceCurrency", "availability"),
            "Organization": ("name", "url", "logo"),
            "FAQPage": ("mainEntity",),
            "VideoObject": ("name", "description", "thumbnailUrl", "uploadDate"),
            "WebSite": ("name", "url"),
        }
    )
    # F: structure and accessibility (extraction detail level 2)
    max_boilerplate_ratio: float = Field(default=0.5, ge=0, le=1)
    max_hidden_ratio: float = Field(default=0.3, ge=0, le=1)
    min_semantic_kinds: int = Field(default=2, ge=0)
    pseudo_list_min_lines: int = Field(default=3, ge=1)
    generic_anchor_texts: tuple[str, ...] = (
        "click here",
        "here",
        "link",
        "this link",
        "more",
        "read more",
        "learn more",
        "details",
        "continue",
        "this",
        "page",
    )
    min_contextual_links: int = Field(default=1, ge=0)
    # I and J: media and page-type heuristics
    how_to_prefixes: tuple[str, ...] = ("how to", "how do", "guide to", "steps to")
    comparison_terms: tuple[str, ...] = (" vs ", " vs. ", "versus", "compar")
    # H: linking
    min_incoming_links: int = Field(default=1, ge=0)
    topic_overlap_max: float = Field(default=0.8, ge=0, le=1)
    # J: retrieval readiness
    max_section_chars: int = Field(default=3000, ge=1)
    dangling_openers: tuple[str, ...] = (
        "this",
        "that",
        "these",
        "those",
        "it",
        "they",
        "such",
        "he",
        "she",
        "as mentioned",
    )
    # K: delivery
    latency_budget_seconds: float = Field(default=2.0, gt=0)
    max_html_bytes: int = Field(default=1_000_000, ge=1)
    # Response state (docs/validation/VALIDATION_POLICY.md). A short page whose title or
    # opening text contains one of these phrases is treated as a bot-challenge or
    # consent interstitial rather than the page the audit meant to fetch. Heuristic.
    interstitial_markers: tuple[str, ...] = (
        "just a moment",
        "attention required",
        "access denied",
        "are you a robot",
        "robot or human",
        "verify you are human",
        "checking your browser",
        "captcha",
        "enable javascript and cookies to continue",
        "unusual traffic",
    )
    interstitial_max_text_chars: int = Field(default=1500, ge=1)
    # Findings and scoring
    measured_confidence: float = Field(default=1.0, ge=0, le=1)
    heuristic_confidence: float = Field(
        default=0.5, ge=0, le=1
    )  # ordinal marker, not a probability
    max_evidence_per_finding: int = Field(default=20, ge=1)
    min_reportable_coverage: float = Field(default=0.5, ge=0, le=1)
