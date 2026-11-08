"""The 120 catalog entries (source of truth; ``configs/feature_catalog.json`` is exported).

Statuses are honest: ``implemented`` and ``partial`` entries have a working check in
``geoptimiser.features.checks``; ``planned`` entries name the data source or stage
that blocks them; ``unavailable`` entries need a capability that is not on the
roadmap yet. IDs and names are stable: never renumber, only add.
"""

from typing import Any

from geoptimiser.features.catalog import (
    CATALOG_VERSION,
    Category,
    FeatureCatalog,
    FeatureDefinition,
    InputSource,
    Overlap,
)
from geoptimiser.schemas import ImplementationStatus, Severity

CATEGORIES = (
    Category(
        code="A",
        name="Crawlability and discovery",
        pillar="technical_health",
        description="Whether crawlers and AI retrieval systems can reach, fetch and follow the site.",
    ),
    Category(
        code="B",
        name="URL health and canonicalization",
        pillar="technical_health",
        description="Whether each page has one clean, stable, canonical address.",
    ),
    Category(
        code="C",
        name="Metadata and search-result presentation",
        pillar="content_quality",
        description="How pages describe themselves to search and answer systems.",
    ),
    Category(
        code="D",
        name="Content clarity and semantic coverage",
        pillar="content_quality",
        description="Whether content states its topic clearly and covers what users ask.",
    ),
    Category(
        code="E",
        name="Evidence, accuracy, trust and freshness",
        pillar="content_quality",
        description="Signals that claims are sourced, attributed and current.",
    ),
    Category(
        code="F",
        name="Content extraction, structure and accessibility",
        pillar="technical_health",
        description="Whether machines can extract the main content and its structure.",
    ),
    Category(
        code="G",
        name="Structured data and entity semantics",
        pillar="technical_health",
        description="Machine-readable descriptions of the page and the entities on it.",
    ),
    Category(
        code="H",
        name="Internal linking and site architecture",
        pillar="technical_health",
        description="How pages connect, so that content can be discovered and understood in context.",
    ),
    Category(
        code="I",
        name="Images, video and other multimodal content",
        pillar="content_quality",
        description="Whether non-text content is described and usable by text-based systems.",
    ),
    Category(
        code="J",
        name="Retrieval and RAG readiness",
        pillar="retrieval_readiness",
        description="Whether content divides into self-contained, attributable passages.",
    ),
    Category(
        code="K",
        name="Technical quality and performance",
        pillar="technical_health",
        description="Delivery characteristics of the page response.",
    ),
    Category(
        code="L",
        name="AI-search visibility and outcomes",
        pillar="ai_visibility",
        description="Observed outcomes in AI-search answers (needs provider data).",
    ),
)
_PILLAR = {c.code: c.pillar for c in CATEGORIES}
_PAGE_EVIDENCE = (
    "One EvidenceRef per result quoting the observed value (or stating its absence) "
    "with the page URL and the fetch time."
)
_SITE_EVIDENCE = "One EvidenceRef per contributing page, origin or file, with its URL."
_IMPL_TESTS = (
    "Unit tests with deterministic fixtures for pass, fail, not_applicable, "
    "not_measured and malformed-input cases; evidence provenance asserted."
)

_Opt = Any


def _f(
    fid: str,
    name: str,
    desc: str,
    why: str,
    measure: str,
    out: str,
    inputs: tuple[InputSource, ...],
    applies: str,
    method: str,
    status: ImplementationStatus,
    *,
    unit: str | None = None,
    scope: str = "page",
    heur: bool = False,
    sev: Severity = "medium",
    scored: bool = True,
    unscored_because: str = "",
    limits: tuple[str, ...] = (),
    cfg: tuple[str, ...] = (),
    blocked: tuple[str, ...] = (),
    overlaps: tuple[tuple[str, str], ...] = (),
    fix: str | None = None,
    evid: str | None = None,
    sevpol: str | None = None,
    evalreq: str = "",
    version: int = 1,
    intent: bool = False,
) -> FeatureDefinition:
    runnable = status in ("implemented", "partial")
    if scored:
        scorepol = (
            "Scored: each measured unit counts pass=1, fail=0; not_applicable, "
            "not_measured and error units are excluded from the denominator and "
            "reported as coverage."
        )
    else:
        scorepol = (
            "Unscored (informational): measured and reported with coverage but "
            f"excluded from scores. {unscored_because}"
        )
    if not runnable:
        scorepol = "Not yet measured, so excluded from scores. " + scorepol
    return FeatureDefinition(
        feature_id=fid,
        category=fid and "ABCDEFGHIJKL"[(int(fid[1:]) - 1) // 10],
        name=name,
        description=desc,
        rationale=why,
        pillar=_PILLAR["ABCDEFGHIJKL"[(int(fid[1:]) - 1) // 10]],
        scope=scope,  # type: ignore[arg-type]
        measurement=measure,
        output_type=out,
        unit=unit,
        inputs=inputs,
        evidence_requirements=evid
        or (_PAGE_EVIDENCE if scope == "page" else _SITE_EVIDENCE),
        applicability=applies,
        method=method,
        implementation_status=status,
        measurable_now=runnable,
        blocked_by=blocked,
        is_heuristic=heur,
        check_version=version if runnable else 0,
        intent_dependent=intent,
        base_severity=sev,
        severity_policy=sevpol
        or f"A failing result has severity `{sev}`; a finding takes the highest severity among its failing results.",
        scored=scored,
        scoring_policy=scorepol,
        limitations=limits or ("None beyond the stated method.",),
        config_keys=cfg,
        test_requirements=(
            _IMPL_TESTS
            if runnable
            else "Contract test: the engine must report not_measured with the blocked_by "
            "reason. "
            + (f"Evaluation before implementing: {evalreq}" if evalreq else "")
        ),
        remediation=fix,
        overlaps=tuple(Overlap(feature_id=i, distinction=d) for i, d in overlaps),
    )


I, P, PL, UN = "implemented", "partial", "planned", "unavailable"
FR, PD, CG, RB, SC = (
    "fetch_record",
    "page_document",
    "crawl_graph",
    "robots_txt",
    "site_configuration",
)
EXT = "extractor_extension"
FEATURES: list[FeatureDefinition] = []
add = FEATURES.append

# --- A: Crawlability and discovery -------------------------------------------------
add(
    _f(
        "F001",
        "HTTP success status",
        "Whether the page request ended in a 2xx response.",
        "Pages that do not return success cannot be read, cited or retrieved.",
        "Final HTTP status of the page fetch.",
        "boolean (2xx)",
        (FR,),
        "Every fetched page. A transport failure or an unfollowed redirect gives no final status, so it is not_measured.",
        "pass if the FetchRecord outcome is success; not_measured for HTTP 429, and for 503 with Retry-After (the server is throttling this crawl, which says nothing about the page); fail for any other http_error (4xx/5xx); otherwise not_measured with the reason.",
        I,
        sev="high",
        fix="Fix the server error or restore/redirect the missing page.",
        limits=(
            "Reflects one fetch from one vantage point at one time; intermittent errors are not detected.",
            "A 403 may be bot blocking of the audit crawler rather than a page defect; it is still reported as a failure because the crawler cannot tell the two apart.",
        ),
        version=2,
    )
)
add(
    _f(
        "F002",
        "Crawlable page links",
        "Whether the page exposes at least one followable (http/https anchor, not rel=nofollow) link.",
        "A page without followable links is a dead end for crawlers discovering the rest of the site.",
        "Count of followable anchors in the extracted document.",
        "count",
        (PD,),
        "Every page with an extracted document.",
        "pass if followable anchors >= min_crawlable_links, else fail. Anchors with rel=nofollow are not followable; javascript:, mailto: and fragment-only links are excluded by extraction. Documents from the older extractor fall back to the plain link list.",
        I,
        cfg=("min_crawlable_links",),
        sev="low",
        overlaps=(
            (
                "F071",
                "F002 is a binary dead-end test; F071 normalises internal links by text length.",
            ),
            (
                "F073",
                "F002 asks whether any followable link exists; F073 reports the internal/external counts.",
            ),
        ),
        limits=(
            "Links created by JavaScript are not in the static HTML and are not seen.",
        ),
        fix="Add normal <a href> links to related pages.",
    )
)
add(
    _f(
        "F003",
        "Robots.txt accessibility",
        "Whether robots.txt can be retrieved (or is cleanly absent) for each origin.",
        "RFC 9309 tells crawlers to treat an unreachable robots.txt (server or network error) as a complete disallow.",
        "HTTP outcome of the robots.txt fetch per origin.",
        "boolean",
        (FR, RB),
        "Each origin whose robots.txt was fetched; not_measured when the crawl did not fetch it.",
        "pass if 2xx or 4xx (RFC 9309: absent means allowed); fail if 5xx; not_measured on transport failure or an unfollowed redirect.",
        I,
        scope="site",
        sev="high",
        fix="Make robots.txt return 200 (or 404 if none is intended), never 5xx.",
        limits=("Does not judge the content of the file; see F004.",),
    )
)
add(
    _f(
        "F004",
        "Robots policy compliance",
        "Whether robots.txt permits the audited page for the configured crawler tokens.",
        "Compliant crawlers obey robots.txt, so a disallow rule keeps them from fetching the page. Whether that is wanted is the site owner's decision.",
        "List of configured user-agent tokens that are disallowed for the page URL.",
        "list of tokens (empty = compliant)",
        (FR, RB),
        "Pages whose origin has a readable robots.txt; not_measured otherwise.",
        "Parse the stored robots.txt with the RFC 9309 matcher (wildcards, longest match) and test the page URL for each token in audit_agent_tokens and ai_crawler_tokens; report `warning` (confirm intent) if any is disallowed. A robots.txt that is unreadable, or whose stored body cannot be read, is not_measured.",
        I,
        cfg=("audit_agent_tokens", "ai_crawler_tokens"),
        sev="low",
        scored=False,
        unscored_because="Blocking a crawler is often a deliberate policy; it is reported as a notice to confirm, not scored as a defect.",
        intent=True,
        version=2,
        fix="Confirm that blocking these agents is intended. If the page should be reachable by them, narrow or remove the matching Disallow rules.",
        limits=(
            "Token list is configuration, not an authoritative registry of AI crawlers; blocking may be intentional.",
            "A notice only: the audit cannot tell whether the block is deliberate.",
        ),
    )
)
add(
    _f(
        "F005",
        "Meta robots directives",
        "Whether the page's meta robots tag forbids indexing.",
        "A noindex directive asks search engines not to index the page; AI systems that draw on those indexes may then not retrieve it (that dependence is not measured here).",
        "Directive tokens in <meta name=robots>.",
        "list of tokens",
        (PD,),
        "Every page with an extracted document. An absent tag means no restriction and passes.",
        "Report `warning` (confirm intent) if the tokens include noindex or none; pass otherwise.",
        I,
        sev="low",
        scored=False,
        unscored_because="noindex is often deliberate (thank-you pages, staging, internal search); it is reported as a notice to confirm, not scored as a defect.",
        intent=True,
        version=2,
        fix="Confirm the restriction is intended. If the page should appear in search results, remove noindex/none.",
        limits=(
            "A notice only: the audit cannot tell whether the directive is deliberate.",
        ),
        overlaps=(
            ("F006", "F005 reads the HTML tag; F006 reads the HTTP header."),
            ("F030", "F005 covers indexing; F030 covers snippet restrictions."),
        ),
    )
)
add(
    _f(
        "F006",
        "X-Robots-Tag directives",
        "Whether the X-Robots-Tag response header forbids indexing.",
        "Header directives apply to any file type, including ones that have no HTML to carry a robots tag.",
        "Directive tokens in the X-Robots-Tag header.",
        "list of tokens",
        (FR,),
        "Every fetched page with a response. Absent header passes.",
        "Split the header on commas; ignore an optional leading 'agent:' scope when reporting; report `warning` (confirm intent) on noindex or none.",
        I,
        sev="low",
        scored=False,
        unscored_because="noindex is often deliberate; it is reported as a notice to confirm, not scored as a defect.",
        intent=True,
        version=2,
        fix="Confirm the restriction is intended. If the page should be indexed, remove noindex/none from the X-Robots-Tag header.",
        limits=(
            "Agent-specific directives are reported but treated as applying to the page.",
            "A notice only: the audit cannot tell whether the directive is deliberate.",
        ),
    )
)
add(
    _f(
        "F007",
        "Sitemap availability",
        "Whether the site declares a sitemap in robots.txt.",
        "Sitemaps help crawlers find pages that internal links do not reach.",
        "Sitemap URLs declared by robots.txt Sitemap: lines.",
        "list of URLs",
        (RB,),
        "Origins with a readable robots.txt.",
        "pass if at least one Sitemap: directive is declared; otherwise not_measured (default sitemap locations are not probed, so absence is not concluded).",
        P,
        scope="site",
        sev="low",
        scored=False,
        unscored_because="Only declaration is checked; the sitemap file itself is not fetched.",
        limits=(
            "Availability of the file is not verified because the crawler does not fetch sitemaps yet.",
        ),
        overlaps=(
            (
                "F008",
                "F007 asks whether a sitemap is declared; F008 compares its URL list with crawled pages.",
            ),
        ),
    )
)
add(
    _f(
        "F008",
        "Sitemap URL coverage",
        "Share of sitemap URLs that were crawled, and of crawled pages listed in the sitemap.",
        "Mismatches reveal undiscovered, orphaned or stale URLs.",
        "Ratio of sitemap URLs found among crawled pages and vice versa.",
        "ratio 0-1",
        ("sitemap", FR),
        "Sites with a fetchable sitemap.",
        "Parse sitemap XML safely and compare normalised URL sets.",
        PL,
        scope="site",
        blocked=(
            "The crawler does not fetch or parse sitemaps (Stage 01 limitation).",
        ),
        evalreq="fixture sitemaps with partial overlap.",
    )
)
add(
    _f(
        "F009",
        "Orphan-page risk",
        "Whether a crawled page has no incoming internal links from other crawled pages.",
        "Pages that nothing links to cannot be found by following links, so link-following crawlers do not reach them.",
        "Number of distinct other pages linking to the page.",
        "count",
        (CG,),
        "Every page except the entry page. Pages found only through a sitemap are not yet considered.",
        "fail if zero distinct other crawled pages link to the page (after following redirects to the final URL). not_measured while any other page's link list is incomplete (truncated, capped or not extracted), because the missing links may point here.",
        P,
        sev="medium",
        version=2,
        cfg=(),
        fix="Link to the page from relevant hub or related pages.",
        limits=(
            "A breadth-first crawl discovers every page through a link from another crawled page, so this check cannot fail on a crawl-discovered page; it does not contribute to the aggregate score until URLs are also discovered by another source (sitemap, F008).",
        ),
        overlaps=(
            (
                "F072",
                "F009 is the zero-incoming risk flag; F072 compares incoming links with a configured minimum.",
            ),
        ),
    )
)
add(
    _f(
        "F010",
        "Crawl depth",
        "Minimum number of link clicks from the entry page to the page.",
        "Pages many clicks from the entry page are reached later by link-following crawlers; any effect on ranking or citation is not measured here.",
        "Shortest link distance from the entry page in the crawled link graph.",
        "count",
        (CG,),
        "Every reachable page; unreachable pages are not_measured.",
        "Breadth-first search over internal links of crawled documents; pass if depth <= max_click_depth. A failure is not_measured while any page's link list is incomplete, because a shorter path may exist.",
        I,
        unit="clicks",
        cfg=("max_click_depth",),
        sev="low",
        version=2,
        fix="Link to the page from pages closer to the entry page.",
        limits=(
            "The threshold is a configurable policy default, not a ranking rule.",
            "The crawl only reaches pages within its own depth bound; when that bound is not larger than max_click_depth the check cannot fail and does not contribute to the aggregate score.",
        ),
    )
)

# --- B: URL health and canonicalization --------------------------------------------
add(
    _f(
        "F011",
        "Canonical tag presence",
        "Whether the page declares a canonical URL.",
        "Without a canonical, duplicates of a page compete and signals are split.",
        "The rel=canonical href.",
        "boolean",
        (PD,),
        "Every page with an extracted document.",
        "pass if canonical_url is present and non-blank; fail if absent or blank.",
        I,
        sev="medium",
        fix='Add <link rel="canonical" href="..."> pointing to the preferred URL.',
        limits=("Canonicals set only by HTTP Link headers are not read.",),
    )
)
add(
    _f(
        "F012",
        "Canonical target validity",
        "Whether the canonical URL is well-formed and, when crawled, a healthy page.",
        "A canonical pointing at a broken, relative or non-indexable URL is ignored or harmful.",
        "Resolved canonical URL and the crawl status of its target.",
        "boolean",
        (PD, FR),
        "Pages that declare a canonical.",
        "Resolve against the page URL; fail if not an absolute http(s) URL, has a fragment, or the crawled target answered with a 404/410-class error or is noindex; pass if the crawled target is healthy. not_measured if the target was not crawled, was redirected away, timed out, or answered with a server error or an access/rate-limit status, because reachability is then unknown.",
        P,
        sev="high",
        version=2,
        fix="Point the canonical at an absolute, indexable, 200-status URL.",
        limits=(
            "Reachability is judged only for canonical targets that were crawled; an uncrawled or unreachable target is reported as not measured, never as a pass.",
        ),
    )
)
add(
    _f(
        "F013",
        "Canonical consistency",
        "Whether the canonical points to itself or to a self-canonical target (no chains or loops).",
        "Chains and loops make it unclear which URL is preferred.",
        "Relationship between the page, its canonical and the target's canonical.",
        "boolean",
        (PD,),
        "Pages that declare a canonical. Non-self canonicals whose target was not crawled are not_measured.",
        "pass if canonical equals the page URL, or the crawled target's own canonical is itself; fail if the target canonicalises elsewhere.",
        I,
        sev="medium",
        fix="Make the final target self-canonical and point all duplicates at it.",
        overlaps=(
            (
                "F012",
                "F012 validates one canonical URL; F013 compares canonicals across pages.",
            ),
        ),
    )
)
add(
    _f(
        "F014",
        "Duplicate page content",
        "Whether another crawled page has identical normalised text.",
        "Duplicates dilute signals and make citations ambiguous.",
        "Pages sharing the SHA-256 of normalised visible text.",
        "list of URLs",
        (PD,),
        "Pages with at least duplicate_min_text_chars of text; shorter pages are not_applicable.",
        "Group pages by hash of lower-cased, whitespace-collapsed text; fail if the group has more than one page.",
        P,
        cfg=("duplicate_min_text_chars",),
        sev="medium",
        fix="Consolidate duplicates with redirects or canonicals, or differentiate the content.",
        limits=("Exact duplicates only; near-duplicates are not detected.",),
        overlaps=(
            ("F022", "F014 compares body text; F022 compares titles."),
            (
                "F080",
                "F014 finds identical text; F080 flags heavily overlapping topics.",
            ),
        ),
    )
)
add(
    _f(
        "F015",
        "Redirect-chain length",
        "Number of redirect hops between the requested URL and the final URL.",
        "Long chains waste crawl budget and risk being abandoned.",
        "Count of followed redirect hops.",
        "count",
        (FR,),
        "Pages whose request was redirected; a page that was not redirected is not_applicable.",
        "pass if hops <= max_redirect_hops; fail above it.",
        I,
        unit="hops",
        cfg=("max_redirect_hops",),
        sev="low",
        version=2,
        fix="Redirect directly to the final URL.",
        limits=("The threshold is a policy default, not a ranking rule.",),
    )
)
add(
    _f(
        "F016",
        "Redirect-loop detection",
        "Whether the redirect chain revisits a URL.",
        "A loop makes the page unreachable.",
        "Whether a hop target equals an earlier URL.",
        "boolean",
        (FR,),
        "Pages that were redirected or ended in too_many_redirects; others are not_applicable.",
        "Resolve each Location against its hop URL; fail if a target was already visited.",
        I,
        sev="high",
        fix="Break the loop so the chain ends at a 200 page.",
        limits=(
            "A chain that exceeds the crawler's hop limit without repeating is reported as no loop.",
        ),
    )
)
add(
    _f(
        "F017",
        "Broken internal links",
        "Internal links on the page whose crawled target returned an HTTP error.",
        "Broken links waste crawler effort and signal neglect.",
        "Broken internal links among those whose targets were crawled.",
        "count",
        (PD, FR, CG),
        "Pages with at least one internal link whose target was crawled; otherwise not_measured.",
        "Map each internal link to its fetch via requested/final URL; fail if any target answered with an HTTP error that says the page is missing (4xx other than 401/403/407/429). Targets that answered 401/403/407/429 or a 5xx are refused or failing, not shown to be missing, so they are neither counted as checked nor as broken.",
        P,
        sev="medium",
        version=2,
        fix="Update or remove links to missing pages.",
        limits=(
            "Only crawled targets are checked; links beyond the crawl limits are unknown, not good.",
            "A target that blocked or throttled the audit agent is not judged.",
        ),
        overlaps=(
            (
                "F079",
                "F017 is per page; F079 describes how broken links concentrate across the site.",
            ),
        ),
    )
)
add(
    _f(
        "F018",
        "URL parameter proliferation",
        "Number of query parameters in the page URL and in the internal URLs the page links to.",
        "Many parameters create duplicate URL variants.",
        "Largest query-parameter count among the page URL and its internal link targets.",
        "count",
        (FR, PD),
        "Every fetched page. Link targets are judged when the page has an extracted document.",
        "pass if the page URL and every internal link target have <= max_query_parameters parameters; fail otherwise. The crawler does not fetch URLs with query strings by default, so linked URLs are inspected without being crawled.",
        I,
        unit="parameters",
        cfg=("max_query_parameters",),
        sev="low",
        version=2,
        fix="Use clean paths; keep tracking and faceting parameters out of linked URLs.",
        limits=(
            "Judged on URL text only; whether a parameter changes the content is not known.",
            "A truncated or capped link list may hide linked URLs with many parameters.",
        ),
    )
)
add(
    _f(
        "F019",
        "URL semantic readability",
        "Whether path segments are human-readable words.",
        "Readable URLs help users and systems understand a page before fetching it.",
        "Share of path segments that look like words.",
        "list of unreadable segments",
        (FR,),
        "Pages with a non-root path.",
        "A segment is unreadable if it is hex/UUID-like, mostly digits, or longer than max_url_segment_chars; fail if any is unreadable.",
        I,
        heur=True,
        cfg=("max_url_segment_chars",),
        sev="low",
        scored=False,
        unscored_because="Readability is a heuristic with no accepted universal criterion.",
        limits=("English-centric heuristic; non-Latin slugs may be misjudged.",),
    )
)
add(
    _f(
        "F020",
        "HTTPS consistency",
        "Whether the page is served over HTTPS and internal links keep HTTPS.",
        "Mixed schemes fragment URLs and weaken trust signals.",
        "Final scheme and count of http:// internal links.",
        "boolean",
        (FR, PD),
        "Every fetched page with a final URL.",
        "fail if the final URL is http, or the extracted document links to the same site over http://.",
        I,
        sev="high",
        fix="Serve every page over HTTPS and update internal links.",
        overlaps=(
            (
                "F110",
                "F020 checks URL schemes; F110 checks transport security headers.",
            ),
        ),
    )
)

# --- C: Metadata and search-result presentation ------------------------------------
add(
    _f(
        "F021",
        "Title presence",
        "Whether the page has a non-empty <title>.",
        "The title is the primary label for a page in search and citation.",
        "The title text.",
        "boolean",
        (PD,),
        "Every page with an extracted document.",
        "pass if the title is present and non-blank; fail if absent or blank.",
        I,
        sev="high",
        fix="Add a unique, descriptive <title>.",
    )
)
add(
    _f(
        "F022",
        "Title uniqueness",
        "Whether the page's title is shared by no other crawled page.",
        "Identical titles make pages indistinguishable in results and citations.",
        "Other pages with the same normalised title.",
        "list of URLs",
        (PD,),
        "Pages with a non-blank title.",
        "Compare lower-cased, whitespace-collapsed titles; fail if another page matches.",
        I,
        sev="medium",
        fix="Give each page a distinct title.",
        overlaps=(("F014", "F022 compares titles; F014 compares body text."),),
    )
)
add(
    _f(
        "F023",
        "Title descriptiveness",
        "Whether the title is more than a generic placeholder.",
        "Generic titles ('Home', 'Untitled') say nothing about the page.",
        "Whether the normalised title matches the generic-title list or has no letters.",
        "boolean",
        (PD,),
        "Pages with a non-blank title.",
        "fail if the title is in generic_titles or has no alphabetic character.",
        P,
        heur=True,
        cfg=("generic_titles",),
        sev="low",
        fix="Name the page's subject in the title.",
        limits=(
            "Heuristic; says nothing about quality beyond placeholder detection. The list is configuration.",
        ),
        overlaps=(
            (
                "F021",
                "F021 asks whether a title exists; F023 asks whether it is a placeholder.",
            ),
        ),
    )
)
add(
    _f(
        "F024",
        "Meta-description presence",
        "Whether the page has a non-empty meta description.",
        "The description often supplies the summary shown with a result.",
        "The meta description text.",
        "boolean",
        (PD,),
        "Every page with an extracted document.",
        "pass if present and non-blank; fail otherwise.",
        I,
        sev="low",
        fix="Add a meta description summarising the page.",
        limits=("Search systems may generate their own snippet regardless.",),
    )
)
add(
    _f(
        "F025",
        "Meta-description uniqueness",
        "Whether the description is shared by no other page.",
        "Duplicated descriptions suggest boilerplate rather than page-specific summaries.",
        "Other pages with the same normalised description.",
        "list of URLs",
        (PD,),
        "Pages with a non-blank description.",
        "Compare normalised descriptions; fail if another page matches.",
        I,
        sev="low",
        fix="Write a description specific to each page.",
    )
)
add(
    _f(
        "F026",
        "Description-content alignment",
        "Whether the description's terms appear in the page text.",
        "A description unrelated to the content misleads users and answer systems.",
        "Share of the description's content terms found in the page text.",
        "ratio 0-1",
        (PD,),
        "Pages with a non-blank description and text.",
        "Tokenise, drop English stopwords, and compute the covered share; pass if >= description_term_coverage_min.",
        P,
        heur=True,
        cfg=("description_term_coverage_min",),
        sev="low",
        limits=(
            "Lexical overlap only; English stopwords; synonyms count as mismatches. Threshold is a policy default to calibrate.",
        ),
    )
)
add(
    _f(
        "F027",
        "Language declaration",
        "Whether <html lang> holds a well-formed language tag.",
        "Language declarations help select language-appropriate processing.",
        "The lang value.",
        "boolean",
        (PD,),
        "Every page with an extracted document.",
        "pass if lang matches a BCP 47-style tag (e.g. en, en-GB); fail if absent, blank or malformed.",
        I,
        sev="low",
        limits=(
            "Syntax only; whether the tag matches the actual language is not checked.",
        ),
    )
)
add(
    _f(
        "F028",
        "Character encoding declaration",
        "Whether the character encoding is declared by the HTTP header or a <meta charset>.",
        "Undeclared encodings risk garbled text in crawlers that guess.",
        "Charset in Content-Type or <meta charset>/http-equiv.",
        "boolean",
        (FR, PD),
        "Every page with a response. A level-1 document cannot show a <meta charset>, so an undeclared header is not_measured for it.",
        "pass if Content-Type has a charset or the document has charset_declared; fail if neither (detail level 2); not_measured without a response or for a level-1 document without a header charset.",
        I,
        sev="low",
        scored=False,
        unscored_because="Many modern servers rely on the UTF-8 default; reported for context.",
        limits=("Does not verify that the declared charset matches the bytes.",),
    )
)
add(
    _f(
        "F029",
        "Viewport configuration",
        "Whether <meta name=viewport> exists with width=device-width and without disabled zoom.",
        "Viewport configuration controls mobile rendering and text scaling.",
        "The viewport content value and its parsed directives.",
        "boolean",
        (PD,),
        "Every page with a level-2 document.",
        "Parse the viewport content into key=value directives; fail if absent, if width is not device-width, or if user-scalable=no / maximum-scale<=1 disables zoom.",
        I,
        sev="low",
        fix='Add <meta name="viewport" content="width=device-width, initial-scale=1"> and do not disable zoom.',
        overlaps=(
            (
                "F106",
                "F029 checks the declared tag; F106 checks actual mobile rendering support.",
            ),
        ),
        limits=("Only the declared tag is judged, not how the page renders.",),
    )
)
add(
    _f(
        "F030",
        "Search snippet restrictions",
        "Whether snippet-limiting directives are set.",
        "nosnippet and max-snippet limit what answer systems may quote.",
        "Snippet directives from meta robots and X-Robots-Tag.",
        "list of directives",
        (PD, FR),
        "Every fetched page.",
        "Report `warning` (confirm intent) if nosnippet or max-snippet:0 is present; pass otherwise.",
        P,
        sev="low",
        scored=False,
        unscored_because="Snippet limits are usually a deliberate publishing choice; reported as a notice to confirm, not scored as a defect.",
        intent=True,
        version=2,
        fix="Confirm the restriction is intended. If the page should be quotable, remove nosnippet / max-snippet:0.",
        limits=(
            "data-nosnippet attributes on elements are not extracted. Restriction may be intentional.",
            "A notice only: the audit cannot tell whether the directive is deliberate.",
        ),
        overlaps=(("F005", "F005 covers indexing; F030 covers quoting."),),
    )
)

# --- D: Content clarity and semantic coverage --------------------------------------
add(
    _f(
        "F031",
        "Main-topic clarity",
        "Whether the single H1 agrees with the title or opening text.",
        "A page whose label, heading and opening disagree has an unclear subject.",
        "Share of H1 terms found in the title or the first text block.",
        "ratio 0-1",
        (PD,),
        "Pages with exactly one H1 and a title; other pages are not_applicable.",
        "Lexical overlap between H1 terms and (title terms plus first text block terms); pass if >= h1_overlap_min.",
        P,
        heur=True,
        cfg=("h1_overlap_min",),
        sev="low",
        limits=(
            "Lexical, English-only heuristic; a deliberately different H1 is flagged.",
        ),
        overlaps=(
            (
                "F035",
                "F035 checks heading structure; F031 checks agreement between title, H1 and opening.",
            ),
        ),
    )
)
add(
    _f(
        "F032",
        "Search-intent coverage",
        "How well the page covers the intents users bring to its topic.",
        "Pages are retrieved for intents; uncovered intents are missed opportunities.",
        "Share of benchmark intents answered.",
        "ratio 0-1",
        ("query_benchmark", "nlp_model"),
        "Pages mapped to a topic with a query benchmark.",
        "Compare page content to the intents of a versioned benchmark.",
        PL,
        blocked=("Query taxonomy and benchmark (Stage 04).",),
        evalreq="labelled intent-coverage set.",
    )
)
add(
    _f(
        "F033",
        "Direct-answer availability",
        "Whether a concise answer appears near the top for the page's main question.",
        "Answer systems favour passages that state the answer plainly.",
        "Presence of an answer-like passage near the top.",
        "boolean",
        ("nlp_model",),
        "Pages with an identifiable main question.",
        "Judge whether the opening passage answers the question.",
        PL,
        blocked=("Needs intent identification and a validated judge model.",),
        overlaps=(
            (
                "F040",
                "F033 asks if the main question is answered up front; F040 counts question/answer structures.",
            ),
        ),
        evalreq="human-labelled answer positions.",
    )
)
add(
    _f(
        "F034",
        "Key-information prominence",
        "Whether key facts appear early in the page.",
        "Important information buried late is less likely to be extracted.",
        "Position of key facts in the text.",
        "ratio 0-1",
        ("nlp_model",),
        "Pages with identifiable key facts.",
        "Locate key facts and measure their position.",
        PL,
        blocked=("Needs key-fact identification (NLP).",),
        evalreq="labelled key facts.",
    )
)
add(
    _f(
        "F035",
        "Heading hierarchy",
        "Whether headings form a clean outline.",
        "Clean outlines make structure legible to people and parsers.",
        "Violations: missing/multiple H1, skipped levels, empty headings.",
        "list of violations",
        (PD,),
        "Pages with an extracted document. A page with no headings fails (missing H1).",
        "Check for exactly one H1, no level skipped when descending, and no empty heading text.",
        I,
        sev="low",
        version=2,
        fix="Use one H1 and descend one level at a time.",
        overlaps=(
            (
                "F059",
                "F035 checks the outline; F059 covers landmarks and accessibility semantics.",
            ),
        ),
    )
)
add(
    _f(
        "F036",
        "Section descriptiveness",
        "Whether headings name their section's content.",
        "Descriptive headings label passages for retrieval.",
        "Share of headings that are non-generic.",
        "ratio 0-1",
        (PD,),
        "Pages with at least one heading.",
        "fail if any heading is empty, has no letters, or is in generic_headings.",
        P,
        heur=True,
        cfg=("generic_headings",),
        sev="low",
        limits=(
            "Placeholder detection only; descriptiveness is not judged semantically.",
        ),
    )
)
add(
    _f(
        "F037",
        "Topical completeness",
        "Whether the page covers the subtopics expected for its subject.",
        "Thin coverage loses to fuller sources.",
        "Share of expected subtopics covered.",
        "ratio 0-1",
        ("nlp_model", "query_benchmark"),
        "Pages with a defined topic.",
        "Compare coverage to a topic outline.",
        PL,
        blocked=("Needs a topic model and reference outlines.",),
        evalreq="expert-labelled subtopic lists.",
    )
)
add(
    _f(
        "F038",
        "Entity coverage",
        "Whether the entities relevant to the topic are named.",
        "Named entities anchor content to the knowledge that answers cite.",
        "Share of expected entities mentioned.",
        "ratio 0-1",
        ("nlp_model",),
        "Pages with a defined topic.",
        "Run entity recognition and compare to expected entities.",
        PL,
        blocked=("Needs entity recognition and an expected-entity source.",),
        evalreq="labelled entity sets.",
    )
)
add(
    _f(
        "F039",
        "Terminology consistency",
        "Whether the same concept is named consistently.",
        "Inconsistent names fragment retrieval.",
        "Variants per concept.",
        "count",
        ("nlp_model",),
        "Pages with repeated concepts.",
        "Cluster term variants.",
        PL,
        blocked=("Needs term clustering (NLP).",),
        evalreq="labelled term variants.",
    )
)
add(
    _f(
        "F040",
        "Question-and-answer coverage",
        "Whether the page structures questions with answers.",
        "Q&A structures match how users query answer systems.",
        "Question headings and FAQ/QA structured data.",
        "count",
        (PD,),
        "Pages with an extracted document; absence is common, so the result is informational.",
        "Count headings ending in '?' and FAQPage/QAPage types; pass if either is present.",
        P,
        heur=True,
        scored=False,
        unscored_because="Not every page should contain Q&A.",
        limits=(
            "Does not check that an answer follows the question or that markup matches visible content.",
        ),
        overlaps=(
            (
                "F033",
                "F040 counts Q&A structures; F033 judges whether the main question is answered.",
            ),
        ),
    )
)

# --- E: Evidence, accuracy, trust and freshness ------------------------------------
add(
    _f(
        "F041",
        "Source citation presence",
        "Whether the page links to external sources.",
        "Cited sources let readers and systems verify claims.",
        "Number of external domains linked.",
        "count",
        (PD,),
        "Pages with at least min_text_chars_for_citation_check characters of text.",
        "pass if at least one link points outside the site; links cannot be classified as citations versus navigation.",
        P,
        heur=True,
        cfg=("min_text_chars_for_citation_check",),
        sev="low",
        scored=False,
        unscored_because="An external link is not necessarily a citation of a claim.",
        limits=("Navigation, social and advertising links count too.",),
        overlaps=(
            (
                "F042",
                "F041 asks if sources are linked; F042 asks whether the linked targets are valid.",
            ),
        ),
    )
)
add(
    _f(
        "F042",
        "Citation-target validity",
        "Whether linked sources are reachable and relevant.",
        "Dead sources undermine evidence.",
        "Status of external citation targets.",
        "ratio 0-1",
        ("external_http",),
        "Pages with external citations.",
        "Fetch citation targets safely.",
        PL,
        blocked=("The crawler does not fetch external URLs.",),
        evalreq="fixture targets with 200/404/redirects.",
    )
)
add(
    _f(
        "F043",
        "Claim-evidence proximity",
        "Whether claims sit near their supporting evidence.",
        "Nearby evidence helps passages stand alone as supported statements.",
        "Share of claims with nearby evidence.",
        "ratio 0-1",
        ("nlp_model",),
        "Pages with factual claims.",
        "Detect claims and nearby evidence.",
        PL,
        blocked=("Needs claim detection (NLP) and evaluation.",),
        evalreq="labelled claim/evidence pairs.",
    )
)
add(
    _f(
        "F044",
        "Quantitative evidence",
        "Whether the page states measurable facts.",
        "Concrete figures are extractable evidence.",
        "Count of quantitative statements.",
        "count",
        ("nlp_model",),
        "Pages with factual claims.",
        "Detect numeric statements with units and context.",
        PL,
        blocked=(
            "A reliable detector needs NLP; naive digit counting would mislabel dates and IDs.",
        ),
        overlaps=(
            (
                "F096",
                "F044 counts numeric evidence; F096 measures how extractable facts are as passages.",
            ),
        ),
        evalreq="labelled numeric claims.",
    )
)
add(
    _f(
        "F045",
        "Methodology transparency",
        "Whether the page explains how data or conclusions were produced.",
        "Methods let readers judge reliability.",
        "Presence of a methodology section.",
        "boolean",
        ("nlp_model",),
        "Pages presenting data or analysis.",
        "Detect methodology statements.",
        PL,
        blocked=("Needs semantic detection; keyword matching is brittle.",),
        evalreq="labelled methodology passages.",
    )
)
add(
    _f(
        "F046",
        "Author attribution",
        "Whether article-type structured data names an author.",
        "Attribution supports accountability.",
        "The author property of Article-type entities.",
        "boolean",
        (PD,),
        "Pages whose structured data declares an article type; others are not_applicable.",
        "pass if an Article-type entity has a non-empty author; fail if absent.",
        P,
        sev="low",
        fix="Add an author to the Article structured data and show a visible byline.",
        limits=("Visible bylines and meta author tags are not read.",),
        overlaps=(
            (
                "F069",
                "F046 checks one signal; F069 checks overall Article property completeness.",
            ),
        ),
    )
)
add(
    _f(
        "F047",
        "Publisher identity",
        "Whether structured data identifies the publisher or organisation.",
        "Publisher identity is a basic trust signal.",
        "Publisher/Organization name in structured data.",
        "boolean",
        (PD,),
        "Pages with extracted structured data of any kind; pages with none are not_applicable here (see F062).",
        "pass if an Organization entity or a publisher property carries a name.",
        P,
        sev="low",
        limits=("Visible footer or about-page identity is not assessed.",),
    )
)
add(
    _f(
        "F048",
        "Publication-date availability",
        "Whether article-type structured data has datePublished.",
        "Dates let systems judge recency.",
        "datePublished value.",
        "boolean",
        (PD,),
        "Article-type pages only.",
        "pass if datePublished is present and non-blank.",
        P,
        sev="low",
        limits=("Visible dates and meta tags are not read.",),
    )
)
add(
    _f(
        "F049",
        "Modification-date availability",
        "Whether a modification date exists.",
        "Modified dates distinguish maintained from abandoned pages.",
        "dateModified or Last-Modified header.",
        "boolean",
        (PD, FR),
        "Article-type pages only.",
        "pass if dateModified or a Last-Modified header exists.",
        P,
        sev="low",
        limits=("Last-Modified from servers is often just the generation time.",),
    )
)
add(
    _f(
        "F050",
        "Freshness consistency",
        "Whether the page's dates are valid and ordered.",
        "Impossible dates undermine trust.",
        "Violations among dates.",
        "list of violations",
        (PD, FR),
        "Pages with both datePublished and dateModified.",
        "fail if a date is unparseable, modified precedes published, or either lies after the fetch time.",
        I,
        sev="low",
        limits=("Does not decide whether content is actually up to date.",),
    )
)

# --- F: Content extraction, structure and accessibility ----------------------------
add(
    _f(
        "F051",
        "Extractable main text",
        "Whether the page yields readable text without scripts.",
        "Text invisible to extractors cannot be cited.",
        "Characters of extracted visible text.",
        "count",
        (PD,),
        "Every page with an extracted document.",
        "pass if text length >= min_extractable_chars.",
        I,
        unit="characters",
        cfg=("min_extractable_chars",),
        sev="high",
        fix="Serve the main content in the initial HTML instead of only via JavaScript.",
        limits=("Navigation text counts; main content is not separated.",),
    )
)
add(
    _f(
        "F052",
        "Main-content signal",
        "Whether a <main>/<article> landmark (or role) identifies the main content.",
        "Landmarks let extractors skip boilerplate and find the content.",
        "Presence of main or article landmarks.",
        "boolean",
        (PD,),
        "Every page with a level-2 document.",
        "pass if a landmark of kind main or article exists (tag or role); fail otherwise.",
        I,
        sev="low",
        fix="Wrap the primary content in <main> (or <article>).",
        overlaps=(
            (
                "F051",
                "F051 checks that text exists; F052 checks that main content is identifiable.",
            ),
        ),
        limits=(
            "Presence only; whether the landmark wraps the right content is not judged.",
        ),
    )
)
add(
    _f(
        "F053",
        "Navigation-to-content ratio",
        "Share of visible text inside navigation, banner, footer or complementary regions.",
        "Boilerplate that dominates the text crowds out the content in passages.",
        "Boilerplate characters / extracted text characters.",
        "ratio 0-1",
        (PD,),
        "Pages with text and at least one landmark; otherwise not_measured (regions cannot be separated).",
        "pass if the share <= max_boilerplate_ratio.",
        I,
        cfg=("max_boilerplate_ratio",),
        sev="low",
        scored=False,
        unscored_because="No accepted threshold; the ratio is context for retrieval readiness.",
        limits=(
            "Characters are approximate (counted per text chunk). Without landmarks the regions are unknown.",
        ),
    )
)
add(
    _f(
        "F054",
        "Hidden-content proportion",
        "Share of page text that is hidden from view (hidden attribute or display:none/visibility:hidden).",
        "Large hidden areas may not be citable and can indicate cloaking or collapsed content.",
        "Hidden characters / (hidden + visible characters).",
        "ratio 0-1",
        (PD,),
        "Pages with any text.",
        "pass if the share <= max_hidden_ratio.",
        I,
        cfg=("max_hidden_ratio",),
        sev="low",
        scored=False,
        unscored_because="Hidden content is often legitimate (menus, accordions); reported for review.",
        limits=(
            "Only the hidden attribute and inline styles are seen; hiding by CSS classes is not.",
            "Whether JavaScript reveals the hidden text after the page loads was not evaluated.",
        ),
    )
)
add(
    _f(
        "F055",
        "Semantic HTML usage",
        "How many kinds of semantic structural elements the page uses.",
        "Semantic elements convey page structure to machines.",
        "Counts of main, article, section, nav, header, footer and aside elements.",
        "counts",
        (PD,),
        "Every page with a level-2 document.",
        "pass if at least min_semantic_kinds distinct structural kinds are present.",
        I,
        cfg=("min_semantic_kinds",),
        sev="low",
        fix="Use semantic elements (main, nav, header, footer, article, section) instead of generic divs.",
        limits=(
            "Counts presence, not correct use. The threshold is a policy default.",
        ),
    )
)
add(
    _f(
        "F056",
        "Table structure",
        "Whether data tables have header cells.",
        "Header cells make table data extractable as labelled facts.",
        "Tables with at least two rows and columns but no <th>.",
        "list of tables",
        (PD,),
        "Pages with non-presentational tables; others are not_applicable.",
        "fail if a data table (>= 2 rows and >= 2 columns, not role=presentation) has no header cells.",
        I,
        sev="low",
        fix="Mark header cells with <th> (and add a <caption> where useful).",
        limits=(
            "Layout tables without role=presentation look like data tables. scope/headers attributes are not read.",
        ),
    )
)
add(
    _f(
        "F057",
        "List structure",
        "Whether list-like content uses real list markup.",
        "List markup makes items individually extractable.",
        "Pseudo-list text lines without real lists.",
        "count",
        (PD,),
        "Pages whose text has list-like lines.",
        "Count text lines that start with a bullet or number marker; fail if there are at least pseudo_list_min_lines of them and no real list with that many items outside navigation.",
        P,
        heur=True,
        cfg=("pseudo_list_min_lines",),
        sev="low",
        scored=False,
        unscored_because="A heuristic over plain text with no accepted threshold.",
        limits=(
            "English-style markers only; markers in the source text of real list items are not present in extracted text.",
        ),
    )
)
add(
    _f(
        "F058",
        "Descriptive anchor text",
        "Whether link text describes its target.",
        "'Click here' carries no meaning for readers, crawlers or passage retrieval.",
        "Share of anchors with generic or empty text.",
        "list of anchors",
        (PD,),
        "Pages with followable anchors.",
        "fail if an anchor has no text (and no image alt) or its text is in generic_anchor_texts.",
        P,
        heur=True,
        cfg=("generic_anchor_texts",),
        sev="low",
        fix="Use link text that names the destination.",
        overlaps=(
            (
                "F078",
                "F058 judges anchor wording alone; F078 judges relevance to the target page.",
            ),
        ),
        limits=(
            "Placeholder detection only; descriptiveness is not judged semantically. English list.",
        ),
    )
)
add(
    _f(
        "F059",
        "Heading and landmark accessibility",
        "Landmark semantics that assistive technology and parsers rely on.",
        "Accessible structure doubles as machine-readable structure.",
        "Landmark problems found.",
        "list of problems",
        (PD,),
        "Every page with a level-2 document.",
        "fail if there is no main landmark, more than one main, or several navigation/complementary landmarks without an accessible label. Heading structure is judged by F035.",
        P,
        sev="low",
        version=2,
        fix="Use one <main> and label repeated landmarks with aria-label.",
        overlaps=(("F035", "F035 checks the heading outline; F059 checks landmarks."),),
        limits=(
            "Heading outline is covered by F035; ARIA beyond landmark labels is not assessed.",
            "A page with no main landmark fails F052 and this check for the same cause; in the aggregate score that cause is counted once (F052).",
        ),
    )
)
add(
    _f(
        "F060",
        "Text-to-markup ratio",
        "Share of the HTML response that is visible text.",
        "A tiny ratio often means a script-driven shell.",
        "Extracted text bytes / stored body bytes.",
        "ratio 0-1",
        (PD, FR),
        "Pages whose stored body is complete (not truncated).",
        "pass if ratio >= min_text_to_markup_ratio.",
        I,
        cfg=("min_text_to_markup_ratio",),
        sev="low",
        scored=False,
        unscored_because="No accepted universal threshold; reported for context.",
        limits=("Threshold is a policy default. Truncated bodies are not_measured.",),
        overlaps=(
            ("F102", "F060 relates text to markup; F102 judges total transfer size."),
            (
                "F108",
                "F060 is a ratio on the raw HTML; F108 compares raw and rendered content.",
            ),
        ),
    )
)

# --- G: Structured data and entity semantics ---------------------------------------
add(
    _f(
        "F061",
        "JSON-LD validity",
        "Whether JSON-LD blocks parse.",
        "Broken blocks are ignored silently.",
        "Count of unparseable JSON-LD blocks.",
        "count",
        (PD,),
        "Pages with at least one JSON-LD block (parsed or broken).",
        "fail only if a complete block is not valid JSON, or a block never closed in a complete document. Blocks skipped by an extraction size/nesting limit, or cut by a truncated response, are not_measured; pass if every block parsed and none was skipped or cut.",
        I,
        sev="medium",
        version=2,
        fix="Fix the JSON syntax of the failing blocks.",
        limits=(
            "Syntax only; semantic validity against schema.org is not checked.",
            "Only a block that is complete and does not parse is reported as invalid; skipped or truncated blocks are reported as not measured.",
        ),
    )
)
add(
    _f(
        "F062",
        "Structured-data type coverage",
        "Whether the page declares any schema.org type.",
        "Types tell systems what a page is.",
        "Declared @type / itemtype values.",
        "list of types",
        (PD,),
        "Every page with an extracted document.",
        "pass if at least one type is declared; fail otherwise.",
        P,
        sev="low",
        limits=("Does not check that the types suit the page.",),
    )
)
add(
    _f(
        "F063",
        "Structured-data property completeness",
        "Whether declared entities have the configured recommended properties.",
        "Missing properties reduce what systems can use.",
        "Missing properties per entity.",
        "list",
        (PD,),
        "Pages with entities whose type is in entity_properties.",
        "For each configured type, require its listed properties; fail if any are missing.",
        P,
        cfg=("entity_properties",),
        sev="low",
        limits=(
            "Property lists are project policy, not Google or schema.org requirements.",
        ),
        overlaps=(
            ("F067", "F063 is generic; F067 is Product-specific."),
            ("F069", "F063 is generic; F069 is Article-specific."),
        ),
    )
)
add(
    _f(
        "F064",
        "Entity identifier availability",
        "Whether organisations and people carry @id or sameAs.",
        "Identifiers let systems link an entity to known records.",
        "Entities with @id or sameAs.",
        "ratio 0-1",
        (PD,),
        "Pages with Organization or Person entities.",
        "fail if any such entity has neither @id nor non-empty sameAs.",
        P,
        sev="low",
        limits=("Does not verify that identifiers resolve or are correct.",),
    )
)
add(
    _f(
        "F065",
        "Entity relationship coverage",
        "Whether entities reference each other.",
        "Relationships express how entities connect.",
        "Edges between entities.",
        "count",
        (PD,),
        "Pages with several entities.",
        "Resolve @id references between entities.",
        PL,
        blocked=("Needs a JSON-LD graph resolver.",),
        evalreq="graph fixtures.",
    )
)
add(
    _f(
        "F066",
        "Organization consistency",
        "Whether Organization names agree across pages.",
        "Conflicting names confuse entity resolution.",
        "Distinct Organization names.",
        "list",
        (PD,),
        "Sites where at least two pages declare an Organization with a name.",
        "fail if more than one distinct normalised name occurs.",
        I,
        scope="site",
        sev="medium",
        fix="Use one canonical organisation name everywhere.",
    )
)
add(
    _f(
        "F067",
        "Product entity completeness",
        "Whether Product entities have the configured properties.",
        "Complete products support comparison and recommendation.",
        "Missing Product properties.",
        "list",
        (PD,),
        "Pages with Product entities.",
        "Check the properties configured for Product.",
        P,
        cfg=("entity_properties",),
        sev="low",
        limits=("Property list is project policy.",),
    )
)
add(
    _f(
        "F068",
        "Offer and pricing completeness",
        "Whether Offers state price, currency and availability.",
        "Incomplete offers cannot be compared or cited.",
        "Missing Offer properties.",
        "list",
        (PD,),
        "Pages with Offer entities (alone or nested in Product.offers).",
        "Check the properties configured for Offer.",
        P,
        cfg=("entity_properties",),
        sev="low",
        limits=("Does not verify prices against visible content.",),
    )
)
add(
    _f(
        "F069",
        "Article metadata completeness",
        "Whether Article entities have the configured properties.",
        "Complete article metadata supports attribution and freshness.",
        "Missing Article properties.",
        "list",
        (PD,),
        "Pages with an article-type entity.",
        "Check the properties configured for the article types.",
        P,
        cfg=("entity_properties", "article_types"),
        sev="low",
        limits=("Property list is project policy.",),
    )
)
add(
    _f(
        "F070",
        "Visible-content consistency",
        "Whether structured-data names appear in visible content.",
        "Markup that contradicts the page is untrustworthy.",
        "Structured names found in title, headings or text.",
        "ratio 0-1",
        (PD,),
        "Pages with structured-data headline/name values.",
        "pass if each distinct headline/name appears (normalised) in title, headings or text; at most 200 distinct values are compared, and a page with more can fail but not pass (not_measured).",
        P,
        heur=True,
        sev="medium",
        limits=(
            "Containment test only; paraphrases fail; other properties are not compared.",
            "At most 200 distinct values per page are compared (bounds the cost of pages with very many JSON-LD entities).",
        ),
        version=2,
    )
)

# --- H: Internal linking and site architecture -------------------------------------
add(
    _f(
        "F071",
        "Internal-link density",
        "Internal links per 1,000 characters of text.",
        "Context for how strongly a page connects to its site.",
        "Internal links / text length.",
        "ratio",
        (PD, CG),
        "Pages with extracted text.",
        "Count internal links and divide by text length.",
        I,
        unit="links per 1000 chars",
        scored=False,
        unscored_because="No universal target density exists.",
        limits=("Navigation links are included.",),
    )
)
add(
    _f(
        "F072",
        "Incoming-link count",
        "Number of other crawled pages that link to the page.",
        "Linked pages are easier to discover.",
        "Distinct incoming linking pages.",
        "count",
        (CG,),
        "Every page except the entry page.",
        "pass if incoming >= min_incoming_links. A failure is not_measured while any other page's link list is incomplete.",
        I,
        cfg=("min_incoming_links",),
        sev="low",
        version=2,
        fix="Add contextual links from related pages.",
        limits=(
            "Only crawled pages count as sources.",
            "With the default minimum of 1 this is the same test as F009 and, on a crawl-discovered page, cannot fail; it then does not contribute to the aggregate score. A higher minimum makes it a real 'weakly linked' check.",
        ),
    )
)
add(
    _f(
        "F073",
        "Outgoing-link count",
        "Internal and external outgoing link counts.",
        "Context for crawl paths and citation behaviour.",
        "Counts of internal and external links.",
        "counts",
        (PD,),
        "Every page with an extracted document.",
        "Classify resolved links by site scope.",
        I,
        scored=False,
        unscored_because="Descriptive; no universal threshold.",
    )
)
add(
    _f(
        "F074",
        "Hub-page identification",
        "Which pages act as hubs.",
        "Hubs distribute discovery to topics.",
        "Pages with high link degree.",
        "list",
        (CG,),
        "Sites with enough pages.",
        "Rank pages by incoming plus outgoing internal links and apply a documented hub definition.",
        PL,
        blocked=("Needs a defensible hub definition and evaluation.",),
        evalreq="labelled hub pages.",
    )
)
add(
    _f(
        "F075",
        "Topic-cluster connectivity",
        "Whether related pages interlink.",
        "Interlinked related pages make topical relationships explicit to link-following crawlers; any effect on authority is unproven.",
        "Connectivity within topic clusters.",
        "ratio 0-1",
        ("nlp_model", CG),
        "Sites with identified topics.",
        "Cluster by topic and measure links.",
        PL,
        blocked=("Needs topic clustering.",),
        evalreq="labelled clusters.",
    )
)
add(
    _f(
        "F076",
        "Important-page accessibility",
        "Whether user-nominated key pages are reachable.",
        "Key pages should be near the entry page.",
        "Depth and status of nominated pages.",
        "list",
        (CG, SC),
        "Audits with a nominated list.",
        "Check status and depth for each.",
        PL,
        blocked=("The audit request has no important-pages field yet.",),
        evalreq="fixture graph.",
    )
)
add(
    _f(
        "F077",
        "Contextual-link coverage",
        "Share of followable internal and external links that sit in body content rather than navigation.",
        "Contextual links carry meaning about the surrounding passage.",
        "Content-region anchors / all anchors.",
        "ratio 0-1",
        (PD,),
        "Pages with anchors.",
        "pass if content-region anchors >= min_contextual_links; the ratio is reported.",
        P,
        cfg=("min_contextual_links",),
        sev="low",
        scored=False,
        unscored_because="No universal target ratio.",
        limits=("A page without landmarks classifies every link as content.",),
    )
)
add(
    _f(
        "F078",
        "Anchor-target relevance",
        "Whether the words in an internal link relate to the page they point at.",
        "Relevant anchors disambiguate targets for retrieval.",
        "Anchors with no term overlap with the crawled target's title or H1.",
        "list of anchors",
        (PD, CG),
        "Pages with internal content anchors whose target was crawled and has a title.",
        "fail if an anchor with content terms shares none with the target's title and H1 terms.",
        P,
        heur=True,
        sev="low",
        scored=False,
        unscored_because="Lexical overlap is a weak proxy for relevance.",
        limits=("Lexical, English-only; synonyms and branded anchors are flagged.",),
    )
)
add(
    _f(
        "F079",
        "Broken-link concentration",
        "How broken internal links cluster across pages.",
        "Concentrated breakage points to a specific template or section.",
        "Total broken, pages affected, share held by the worst page.",
        "summary",
        (PD, FR, CG),
        "Sites where at least one internal link target was crawled.",
        "Aggregate F017-style broken-link counts across pages; fail if any exist.",
        P,
        scope="site",
        sev="low",
        scored=False,
        unscored_because="Duplicates F017's signal at site level.",
        limits=("Only crawled targets are considered.",),
        overlaps=(
            ("F017", "F017 is per page; F079 aggregates and reports concentration."),
        ),
    )
)
add(
    _f(
        "F080",
        "Cross-page topic redundancy",
        "Whether pages' titles and H1s overlap heavily.",
        "Overlapping pages compete for the same query.",
        "Pairs of pages with high title/H1 term overlap.",
        "list of pairs",
        (PD,),
        "Sites with at least two pages that have titles.",
        "Jaccard similarity of title+H1 terms; fail if >= topic_overlap_max.",
        P,
        scope="site",
        heur=True,
        cfg=("topic_overlap_max",),
        sev="low",
        scored=False,
        unscored_because="Overlap is a heuristic prompt for review, not a defect.",
        limits=("Title/H1 only; English stopwords.",),
        overlaps=(
            (
                "F014",
                "F014 is identical body text; F080 is overlapping subject labels.",
            ),
            ("F022", "F022 is identical titles; F080 is similar title/H1 term sets."),
        ),
    )
)

# --- I: Images, video and other multimodal content ---------------------------------
_IMG = ("Stage 02 does not extract image elements.",)
add(
    _f(
        "F081",
        "Image alternative text",
        "Whether informative images have alt text.",
        "Alt text makes images usable by text-based systems and assistive technology.",
        "Non-decorative images with no alt attribute.",
        "list of images",
        (PD,),
        'Pages with images. An empty alt (alt="") marks a decorative image and passes.',
        "fail if any visible image has no alt attribute and is not marked decorative (role=presentation/none, aria-hidden).",
        I,
        sev="medium",
        fix='Add descriptive alt text, or alt="" for purely decorative images.',
        limits=("Presence only; whether the text describes the image is not judged.",),
    )
)
add(
    _f(
        "F082",
        "Image filename descriptiveness",
        "Whether image filenames look like words rather than camera or hash names.",
        "Filenames are weak but real context for images.",
        "Images with opaque filenames.",
        "list of images",
        (PD,),
        "Pages with images that have a URL.",
        "fail if a filename stem is hex/UUID-like, mostly digits, or a camera/screenshot pattern such as IMG_1234.",
        P,
        heur=True,
        sev="low",
        scored=False,
        unscored_because="A heuristic with little evidence of effect.",
        limits=("English-centric pattern list; descriptiveness is not judged.",),
    )
)
add(
    _f(
        "F083",
        "Image dimension availability",
        "Whether images declare width and height.",
        "Declared dimensions let browsers and renderers reserve space.",
        "Images missing width or height.",
        "list of images",
        (PD,),
        "Pages with images that have a URL.",
        "fail if a visible image lacks a numeric width or height attribute.",
        I,
        sev="low",
        fix="Add width and height attributes matching the image's intrinsic size.",
        limits=("Attributes only; CSS-set dimensions are not seen.",),
    )
)
add(
    _f(
        "F084",
        "Image loading behavior",
        "Whether the first content image is lazy-loaded.",
        "Lazy-loading the first (likely largest) image can delay rendering.",
        "The loading attribute of the first content image.",
        "string",
        (PD,),
        "Pages with a non-decorative image outside navigation.",
        "fail if the first such image has loading=lazy.",
        P,
        heur=True,
        sev="low",
        scored=False,
        unscored_because="Without rendering, the first image may not be the one above the fold.",
        limits=("Document order is a proxy for position on screen.",),
    )
)
add(
    _f(
        "F085",
        "Image context alignment",
        "Whether images relate to the surrounding text.",
        "Aligned images support the page's meaning.",
        "Image/text alignment.",
        "ratio 0-1",
        ("browser_render", "nlp_model"),
        "Pages with images.",
        "Compare image content to text.",
        UN,
        blocked=(
            "Needs a vision model and a validated evaluation; not on the roadmap.",
        ),
        evalreq="human-labelled image/text pairs.",
    )
)
add(
    _f(
        "F086",
        "Video transcript availability",
        "Whether pages with video offer a transcript.",
        "Transcripts make video content retrievable as text.",
        "Presence of a transcript heading, link or text.",
        "boolean",
        (PD,),
        "Pages with video or video embeds.",
        "pass if a heading, anchor text or the page text contains 'transcript'; fail otherwise.",
        P,
        heur=True,
        sev="low",
        scored=False,
        unscored_because="Keyword detection is brittle.",
        limits=(
            "English keyword only; a transcript that is not labelled as such is missed.",
        ),
    )
)
add(
    _f(
        "F087",
        "Video caption availability",
        "Whether <video> elements have caption or subtitle tracks.",
        "Captions provide text and accessibility for video.",
        "<video> elements without a captions/subtitles <track>.",
        "list of videos",
        (PD,),
        "Pages with video. Embedded players (iframes) cannot be inspected and are not_measured.",
        "fail if any <video> has no <track kind=captions|subtitles>; pass if all have; not_measured if only embeds exist.",
        I,
        sev="low",
        fix='Add a <track kind="captions"> element to each video.',
        limits=("Captions inside embedded players are not visible from the page.",),
    )
)
add(
    _f(
        "F088",
        "Video metadata completeness",
        "Whether VideoObject structured data accompanies video and has the configured properties.",
        "Video metadata describes content that text extractors cannot read.",
        "Missing VideoObject properties.",
        "list",
        (PD,),
        "Pages with video or video embeds.",
        "fail if there is no VideoObject entity, or one lacks properties configured for VideoObject.",
        P,
        cfg=("entity_properties",),
        sev="low",
        limits=(
            "Property list is project policy. Does not match each VideoObject to a specific video.",
        ),
    )
)
add(
    _f(
        "F089",
        "Audio transcript availability",
        "Whether pages with audio offer a transcript.",
        "Transcripts make audio retrievable as text.",
        "Presence of a transcript heading, link or text.",
        "boolean",
        (PD,),
        "Pages with <audio> elements.",
        "pass if a heading, anchor text or the page text contains 'transcript'; fail otherwise.",
        P,
        heur=True,
        sev="low",
        scored=False,
        unscored_because="Keyword detection is brittle.",
        limits=("English keyword only; audio in embedded players is not detected.",),
    )
)
add(
    _f(
        "F090",
        "Multimodal content dependence",
        "Share of meaning that exists only in non-text media.",
        "Media-only content is invisible to text retrieval.",
        "Text equivalents for media.",
        "ratio 0-1",
        (EXT, "nlp_model"),
        "Pages with media.",
        "Compare media and text content.",
        PL,
        blocked=("Needs media extraction and judgement.",),
        evalreq="labelled pages.",
    )
)

# --- J: Retrieval and RAG readiness ------------------------------------------------
add(
    _f(
        "F091",
        "Chunkable section structure",
        "Whether the text divides into heading-delimited sections of manageable size.",
        "Retrieval systems split pages into passages; headings give natural boundaries.",
        "Sections found and the longest section's size.",
        "count and characters",
        (PD,),
        "Pages with text and at least one locatable heading; otherwise not_measured.",
        "Locate each heading line in order, split the text there, and fail if any section exceeds max_section_chars.",
        P,
        heur=True,
        cfg=("max_section_chars",),
        unit="characters",
        sev="low",
        limits=(
            "Section size limit is a configurable policy default, not a retrieval requirement; headings must appear as their own text lines.",
        ),
    )
)
add(
    _f(
        "F092",
        "Section self-containment",
        "Whether sections open without unresolved references.",
        "Passages retrieved alone must make sense.",
        "Sections starting with a dangling reference word.",
        "list of headings",
        (PD,),
        "Pages with at least two locatable sections.",
        "fail if the first sentence of a section starts with a word in dangling_openers (e.g. 'This', 'It').",
        P,
        heur=True,
        cfg=("dangling_openers",),
        sev="low",
        limits=(
            "English-only lexical heuristic; many valid openings begin with 'This'.",
        ),
    )
)
add(
    _f(
        "F093",
        "Definition availability",
        "Whether key terms are defined.",
        "Definitions are high-value passages.",
        "Definitional sentences.",
        "count",
        ("nlp_model",),
        "Pages introducing a concept.",
        "Detect definitional sentence patterns for terms the page introduces.",
        PL,
        blocked=("Needs concept identification and a validated detector.",),
        evalreq="labelled definitions.",
    )
)
add(
    _f(
        "F094",
        "Procedural-step clarity",
        "Whether how-to pages present their steps as an ordered sequence.",
        "Ordered steps are directly extractable answers.",
        "Ordered lists or 'Step N' markers on how-to pages.",
        "count",
        (PD,),
        "Pages whose title or H1 starts with a how-to prefix; others are not_applicable.",
        "pass if a non-navigation ordered list has >= 2 items, or the text has >= 2 'Step N' lines; fail otherwise.",
        P,
        heur=True,
        cfg=("how_to_prefixes",),
        sev="low",
        scored=False,
        unscored_because="Page type is inferred from the title.",
        limits=(
            "Page type comes from title prefixes (English); steps in other markup are missed.",
        ),
    )
)
add(
    _f(
        "F095",
        "Comparison structure",
        "Whether comparison pages use a table with several columns.",
        "Structured comparisons are extractable as facts.",
        "Data tables with at least two columns on comparison pages.",
        "count",
        (PD,),
        "Pages whose title or H1 contains a comparison term; others are not_applicable.",
        "pass if a non-presentational table with >= 2 rows and >= 2 columns exists; fail otherwise.",
        P,
        heur=True,
        cfg=("comparison_terms",),
        sev="low",
        scored=False,
        unscored_because="Page type is inferred from the title.",
        limits=(
            "Page type comes from title terms (English); parallel structure in lists is not recognised.",
        ),
    )
)
add(
    _f(
        "F096",
        "Fact extractability",
        "Whether facts are stated in self-contained sentences.",
        "Atomic facts are quotable.",
        "Share of facts that are self-contained.",
        "ratio 0-1",
        ("nlp_model",),
        "Pages with factual content.",
        "Segment and judge facts.",
        PL,
        blocked=("Needs fact segmentation and evaluation.",),
        evalreq="labelled facts.",
    )
)
add(
    _f(
        "F097",
        "Answer-context proximity",
        "Whether answers sit next to the context they need.",
        "Distant context breaks retrieved passages.",
        "Distance between answer and context.",
        "characters",
        ("nlp_model",),
        "Pages with answers.",
        "Measure the character distance between each answer and the context it relies on.",
        PL,
        blocked=("Needs answer identification (NLP).",),
        evalreq="labelled answer contexts.",
    )
)
add(
    _f(
        "F098",
        "Entity disambiguation",
        "Whether ambiguous entity names are disambiguated.",
        "Ambiguous names can make a retrieval system match the wrong entity.",
        "Ambiguous names left unresolved.",
        "list",
        ("nlp_model",),
        "Pages naming ambiguous entities.",
        "Detect ambiguous entity mentions and check whether context disambiguates them.",
        PL,
        blocked=("Needs entity recognition and a knowledge source.",),
        evalreq="labelled ambiguous mentions.",
    )
)
add(
    _f(
        "F099",
        "Source-boundary clarity",
        "Whether passages carry their source, author and date.",
        "Cited passages need attributable boundaries.",
        "Provenance fields per passage.",
        "ratio 0-1",
        (PD,),
        "Pages split into passages.",
        "Combine passage and page metadata.",
        PL,
        blocked=("Needs a passage model (chunking is a later stage).",),
        evalreq="passage fixtures.",
    )
)
add(
    _f(
        "F100",
        "Retrieval-query coverage",
        "How well the content is retrieved for benchmark queries.",
        "Retrievability is the practical test.",
        "Retrieval rank/recall per query.",
        "ratio 0-1",
        ("query_benchmark",),
        "Audits with a benchmark and a retrieval index.",
        "Run queries against an index.",
        PL,
        blocked=("Query benchmark (Stage 04) and retrieval index (Stage 08).",),
        evalreq="retrieval evaluation set.",
    )
)

# --- K: Technical quality and performance ------------------------------------------
add(
    _f(
        "F101",
        "Response latency",
        "Wall-clock time of the page fetch.",
        "Slow responses risk timeouts in crawlers and agents.",
        "Seconds between fetch start and completion.",
        "seconds",
        (FR,),
        "Pages with a recorded response.",
        "pass if duration <= latency_budget_seconds.",
        P,
        unit="seconds",
        cfg=("latency_budget_seconds",),
        sev="low",
        scored=False,
        unscored_because="One crawler vantage point; includes redirects and body download.",
        limits=("Not time-to-first-byte; includes DNS, redirects and streaming.",),
    )
)
add(
    _f(
        "F102",
        "Response-size efficiency",
        "Size of the stored HTML response.",
        "Very large responses slow retrieval and may be truncated.",
        "Stored body bytes and whether it was truncated.",
        "bytes",
        (FR,),
        "Pages with a stored body.",
        "fail if the body was truncated or exceeds max_html_bytes.",
        P,
        unit="bytes",
        cfg=("max_html_bytes",),
        sev="low",
        scored=False,
        unscored_because="Threshold is a policy default.",
        limits=("HTML only; subresources are not measured.",),
    )
)
add(
    _f(
        "F103",
        "Compression support",
        "Whether the server compresses responses.",
        "Compression reduces transfer cost.",
        "Content-Encoding of a compressed response.",
        "boolean",
        (FR,),
        "HTML pages.",
        "Request with Accept-Encoding and inspect.",
        PL,
        blocked=("The crawler requests identity encoding by design.",),
        evalreq="fixture servers.",
    )
)
add(
    _f(
        "F104",
        "Cache-header configuration",
        "Whether the response sets Cache-Control.",
        "Explicit caching policy aids efficient re-fetching.",
        "Cache-Control header.",
        "boolean",
        (FR,),
        "Pages with a response.",
        "pass if Cache-Control is present and non-blank.",
        I,
        sev="informational",
        scored=False,
        unscored_because="Caching is not a GEO requirement; reported for context.",
        limits=("Expires is not recorded.",),
    )
)
add(
    _f(
        "F105",
        "ETag and Last-Modified availability",
        "Whether validators exist.",
        "Validators enable conditional re-fetch.",
        "ETag / Last-Modified headers.",
        "boolean",
        (FR,),
        "Pages with a response.",
        "pass if either header is present.",
        I,
        sev="informational",
        scored=False,
        unscored_because="Validators are not a GEO requirement; reported for context.",
    )
)
add(
    _f(
        "F106",
        "Mobile viewport support",
        "Whether the page renders usably on mobile.",
        "Mobile experience affects reach.",
        "Rendered mobile layout checks.",
        "boolean",
        ("browser_render",),
        "HTML pages.",
        "Render at mobile width.",
        PL,
        blocked=("Needs browser instrumentation.",),
        evalreq="rendered fixtures.",
    )
)
add(
    _f(
        "F107",
        "Core Web Vitals",
        "Real-user LCP, INP and CLS.",
        "Experience metrics reflect real use.",
        "Field metrics.",
        "milliseconds/score",
        ("rum",),
        "Origins with field data.",
        "Read field data for LCP, INP and CLS from a real-user measurement source.",
        UN,
        blocked=("Needs real-user data or lab instrumentation; not on the roadmap.",),
        evalreq="validated measurement source.",
    )
)
add(
    _f(
        "F108",
        "JavaScript content dependence",
        "How much content exists only after JavaScript runs.",
        "Content absent from raw HTML is missed by many crawlers.",
        "Raw vs rendered text difference.",
        "ratio 0-1",
        ("browser_render",),
        "HTML pages.",
        "Compare raw and rendered text.",
        PL,
        blocked=("Needs a safe headless rendering environment.",),
        evalreq="static vs client-rendered fixtures.",
    )
)
add(
    _f(
        "F109",
        "Resource failure signals",
        "Failures loading page subresources.",
        "Failing resources may hide content.",
        "Failed subresource requests.",
        "count",
        ("browser_render",),
        "HTML pages.",
        "Record failed requests.",
        PL,
        blocked=("Needs subresource fetching or rendering.",),
        evalreq="fixture pages.",
    )
)
add(
    _f(
        "F110",
        "Security transport configuration",
        "Whether the page was served over HTTPS with an HTTP Strict-Transport-Security policy.",
        "HTTPS protects the integrity of what crawlers and readers receive; HSTS (RFC 6797) tells clients to keep using HTTPS. Neither is an established AI-search ranking or citation factor.",
        "Final URL scheme and the Strict-Transport-Security header (max-age directive).",
        "object (scheme, hsts present, max-age)",
        (FR,),
        "Pages with an HTTP response.",
        "pass if the final URL is https and the response carries Strict-Transport-Security with max-age > 0 (RFC 6797 section 6.1.1); fail if the page was served over plain http, or over https without a usable HSTS policy (missing, unparsable max-age, or max-age=0).",
        I,
        sev="informational",
        scored=False,
        unscored_because="Transport security is a site-hygiene property, not a demonstrated GEO factor; reported for context.",
        limits=(
            "Reads the header on the final response only; it does not check HSTS preload-list membership, certificate quality, TLS versions or other security headers.",
            "HSTS is ignored by browsers when sent over plain http (RFC 6797 section 8.1), so an http page fails regardless of the header.",
        ),
        fix="Serve every page over HTTPS and send Strict-Transport-Security: max-age=31536000 (add includeSubDomains only once every subdomain is HTTPS).",
        evalreq="fixture headers: https with and without HSTS, max-age=0, malformed max-age, plain http.",
    )
)

# --- L: AI-search visibility and outcomes ------------------------------------------
_AI = ("AI-search provider adapters and visibility data (Stage 05/06).",)
for fid, name, why, out in (
    (
        "F111",
        "AI-answer mention rate",
        "Share of benchmark answers mentioning the brand.",
        "ratio 0-1",
    ),
    ("F112", "Citation frequency", "How often the site is cited in answers.", "count"),
    (
        "F113",
        "Unique cited-page coverage",
        "Distinct pages of the site that are cited.",
        "count",
    ),
    (
        "F114",
        "Citation prominence",
        "Position and prominence of citations in answers.",
        "score",
    ),
    (
        "F115",
        "Answer factual coverage",
        "Share of key facts present in answers.",
        "ratio 0-1",
    ),
    (
        "F116",
        "Citation-to-claim support",
        "Whether cited pages support the claims they are attached to.",
        "ratio 0-1",
    ),
    (
        "F117",
        "Citation absorption",
        "How much of an answer is attributable to cited sources.",
        "ratio 0-1",
    ),
    (
        "F118",
        "Cross-run consistency",
        "Stability of outcomes across repeated runs.",
        "ratio 0-1",
    ),
    (
        "F119",
        "Query coverage",
        "Share of benchmark queries answered with any visibility.",
        "ratio 0-1",
    ),
    (
        "F120",
        "Before/after visibility change",
        "Change in visibility metrics after an approved change.",
        "difference with uncertainty",
    ),
):
    add(
        _f(
            fid,
            name,
            why,
            "Observed outcomes are the final test of GEO work; they must be measured, not inferred from site properties.",
            why,
            out,
            ("ai_provider", "query_benchmark")
            if fid != "F120"
            else ("ai_provider", "prior_audit"),
            "Audits with provider data for a versioned benchmark.",
            "Computed from annotated provider responses.",
            PL,
            scope="audit",
            blocked=_AI + (("Baseline audit (Stage 15).",) if fid == "F120" else ()),
            evid="EvidenceRef per provider response or citation, with provider, model and query-set version.",
            evalreq="mock-provider fixtures with known mentions and citations.",
            limits=(
                "Correlation between site features and visibility is not causation.",
            ),
        )
    )


def build_catalog() -> FeatureCatalog:
    return FeatureCatalog(
        version=CATALOG_VERSION, categories=CATEGORIES, features=tuple(FEATURES)
    )


CATALOG = build_catalog()
