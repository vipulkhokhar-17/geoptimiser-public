"""Programmatic discovery of checks that read the same data the same way.

A static view of each registered check: which attributes of the page, document, fetch
record, link graph and configuration its function body touches. Two checks with the
same data signature are *candidates* for double counting; whether they really are is a
judgment recorded in ``OVERLAP_DECISIONS`` (and enforced by a test), because identical
inputs can still answer different questions and different inputs can answer the same
one. Semantic overlaps that static comparison cannot see are listed in the same table.
"""

import ast
import inspect
import textwrap
from dataclasses import dataclass
from itertools import combinations

from geoptimiser.features.registry import CHECKS, default_registry


@dataclass(frozen=True)
class Signature:
    feature_id: str
    data: frozenset[str]
    config: frozenset[str]


def _chains(tree: ast.AST, roots: set[str]) -> set[str]:
    """Attribute paths such as ``doc.title`` or ``page.fetch.headers`` below ``roots``."""
    found: set[str] = set()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Attribute):
            parts: list[str] = []
            cur: ast.AST = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in roots:
                found.add(".".join([cur.id, *reversed(parts)]))
                return
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)
    return found


def signature(feature_id: str) -> Signature:
    fn = CHECKS[feature_id].fn
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    paths = _chains(tree, {"doc", "page", "ctx", "_doc"})
    config = {p.split(".")[-1] for p in paths if p.startswith("ctx.config.")}
    # Normalise aliases: `doc.x` and `page.document.x` are the same data.
    data = {
        p.replace("page.document.", "doc.").replace("_doc.", "doc.")
        for p in paths
        if not p.startswith("ctx.config.")
    }
    # Drop bare containers that every check touches.
    data -= {"page.fetch", "page.document", "page.key", "page.url", "ctx.config"}
    return Signature(feature_id, frozenset(data), frozenset(config))


def signatures() -> dict[str, Signature]:
    return {fid: signature(fid) for fid in sorted(CHECKS)}


def candidate_pairs(min_jaccard: float = 1.0) -> list[tuple[str, str, float]]:
    """Pairs of checks whose data and configuration signatures match.

    ``min_jaccard`` is the overlap of the data sets (1.0 = identical); configuration
    keys must be identical. Checks with an empty data signature (they read only the
    fetch record) are compared on configuration alone and reported at 1.0 only if
    both are empty and the function bodies are textually similar enough to matter.
    """
    sigs = signatures()
    out = []
    for a, b in combinations(sorted(sigs), 2):
        sa, sb = sigs[a], sigs[b]
        if sa.config != sb.config or not (sa.data or sb.data):
            continue
        union = sa.data | sb.data
        j = len(sa.data & sb.data) / len(union) if union else 0.0
        if j >= min_jaccard:
            out.append((a, b, round(j, 3)))
    return out


EXACT = "exact duplicate (under stated configuration)"
SHARED = "distinct measurements sharing one underlying cause"
RELATED = "related, independently useful"
SAME_DATA = "same inputs, different question"
OVEREMPHASIS = "combined score could over-emphasise one property"
NON_DISCRIMINATING = "not a duplicate: both cannot fail under default configuration"

# Decision for every candidate pair and every named or declared overlap. A new
# candidate pair without an entry here fails tests/validation/test_overlap.py. "Score
# effect" says what the aggregate does about it; the evidence is in the tests named.
OVERLAP_DECISIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("F009", "F072"): (
        EXACT,
        "F072 with min_incoming_links=1 is the same test as F009 (both read the "
        "incoming-link set; proven in tests/features/test_evidence_policy.py). Score "
        "effect: unit-level overlap rule counts equal-status results once; in a "
        "link-discovered crawl both are excluded (cannot fail by construction). At "
        "min_incoming_links>=2 F072 is a different question and counts on its own.",
    ),
    ("F052", "F059"): (
        SHARED,
        "A page with no <main> fails F052 and F059's missing-main sub-test for one "
        "cause. Score effect: that F059 failure is counted once under F052 "
        "(contribution.UNIT_OVERLAPS); F059's other sub-tests and a page whose F052 "
        "passes thanks to <article> still count on their own.",
    ),
    ("F010", "F018"): (
        NON_DISCRIMINATING,
        "The earlier audit paired these as duplicates. They are not: F010 reads the "
        "link graph, F018 reads URL query strings. The real shared defect was that "
        "neither could fail under the default crawl (depth 2 <= limit 3; query URLs "
        "never fetched). F018 was revised to inspect linked URLs; F010 is excluded from "
        "the aggregate while crawl depth <= limit.",
    ),
    ("F005", "F006"): (
        SAME_DATA,
        "Meta tag vs HTTP header; a site can set noindex either way. Both are "
        "unscored notices, so nothing is double counted; both findings are kept because "
        "the fix differs.",
    ),
    ("F005", "F030"): (
        RELATED,
        "Indexing vs quoting restrictions; independent choices. Unscored notices.",
    ),
    ("F011", "F012"): (
        RELATED,
        "Presence vs validity of a canonical; F012 is not applicable when F011 fails.",
    ),
    ("F011", "F013"): (
        RELATED,
        "Presence vs chain/loop; F013 is not applicable when F011 fails.",
    ),
    ("F012", "F013"): (
        SAME_DATA,
        "Both resolve the canonical and look up the target (same signature); F012 asks "
        "'is the target healthy', F013 asks 'does the target point elsewhere'. A broken "
        "target can fail only F012; a chain can fail only F013. Independent.",
    ),
    ("F012", "F078"): (
        SAME_DATA,
        "Static-signature match only: both call page_for(); F078 compares anchor text "
        "with target titles. Unrelated questions.",
    ),
    ("F013", "F078"): (SAME_DATA, "Static-signature match only; unrelated questions."),
    ("F003", "F007"): (
        SAME_DATA,
        "Both read robots.txt. F003 asks whether it is reachable; F007 whether it "
        "declares sitemaps. Independent; F007 is unscored.",
    ),
    ("F020", "F073"): (
        SAME_DATA,
        "Both read the link list: F020 judges insecure links, F073 only counts links "
        "(descriptive, always passes, unscored). No double counting.",
    ),
    ("F049", "F104"): (
        SAME_DATA,
        "Static-signature match only (response headers): Last-Modified as a date vs "
        "Cache-Control presence. Unrelated.",
    ),
    ("F066", "F079"): (
        SAME_DATA,
        "Static-signature match only (cross-page loops): organisation names vs broken "
        "links. Unrelated.",
    ),
    ("F017", "F079"): (
        SHARED,
        "F079 summarises the same broken-link set as F017 per site. F079 is unscored, so "
        "the aggregate counts the broken links once (F017).",
    ),
    ("F021", "F022"): (
        RELATED,
        "Presence vs uniqueness; F022 is not applicable without a title.",
    ),
    ("F021", "F023"): (
        RELATED,
        "Presence vs placeholder text; F023 is not applicable without a title.",
    ),
    ("F024", "F025"): (RELATED, "Presence vs uniqueness of the description."),
    ("F024", "F026"): (RELATED, "Presence vs agreement with the page text."),
    ("F035", "F036"): (
        RELATED,
        "Outline shape vs heading wording; empty headings are reported by both (F035: 'empty hN', F036: placeholder/no letters). Accepted: both are low severity and one is heuristic.",
    ),
    ("F035", "F059"): (RELATED, "Heading outline vs landmarks; no shared input."),
    ("F051", "F060"): (
        OVEREMPHASIS,
        "A script-built page fails F051 (little text) and F060 (low text share). F060 is unscored, so the aggregate counts the cause once.",
    ),
    ("F051", "F052"): (RELATED, "Is there text vs is the main content identifiable."),
    ("F052", "F055"): (
        OVEREMPHASIS,
        "A page without any landmarks fails F052, F055 (<2 kinds of semantic element) "
        "and F059. F052/F059 are deduplicated; F055 is kept because a page can have "
        "header/nav/footer yet no <main>, so it is not implied by F052. Documented "
        "risk: div-soup pages are penalised up to twice. No evidence yet that a "
        "stronger adjustment is warranted.",
    ),
    ("F053", "F054"): (RELATED, "Navigation share vs hidden share; both unscored."),
    ("F002", "F077"): (
        RELATED,
        "Any followable link vs a link in body content; both read anchors.",
    ),
    ("F071", "F073"): (SAME_DATA, "Both descriptive and always pass; unscored."),
    ("F033", "F040"): (
        RELATED,
        "Planned direct-answer check vs implemented question-heading signal.",
    ),
    ("F044", "F096"): (
        SHARED,
        "Both planned; both would need fact detection. Decide whether to merge before implementing.",
    ),
    ("F014", "F022"): (
        RELATED,
        "Duplicate body text vs duplicate title; independent evidence.",
    ),
    ("F015", "F016"): (
        RELATED,
        "Chain length vs loop; F016 is a hard error, F015 a threshold.",
    ),
    ("F002", "F071"): (
        SAME_DATA,
        "Followable-link presence vs descriptive link density; F071 always passes and is unscored.",
    ),
    ("F002", "F073"): (
        SAME_DATA,
        "Followable-link presence vs descriptive link counts; F073 always passes and is unscored.",
    ),
    ("F007", "F008"): (
        RELATED,
        "Sitemap declared (implemented, unscored) vs sitemap URL coverage (planned).",
    ),
    ("F014", "F080"): (
        RELATED,
        "Identical body text vs overlapping title/H1 terms; F080 is unscored.",
    ),
    ("F020", "F110"): (
        RELATED,
        "HTTPS consistency vs planned transport-security headers.",
    ),
    ("F022", "F080"): (
        OVEREMPHASIS,
        "Duplicate titles (F022, scored) also raise F080 title/H1 overlap (unscored); counted once in the aggregate.",
    ),
    ("F029", "F106"): (
        RELATED,
        "Viewport tag (implemented) vs planned rendered mobile usability; F106 is a distinct feature only if it measures rendered layout.",
    ),
    ("F031", "F035"): (
        RELATED,
        "H1/title agreement vs outline shape; F031 needs exactly one H1, so a multi-H1 page fails F035 and is not applicable to F031.",
    ),
    ("F041", "F042"): (
        RELATED,
        "External-link presence (unscored) vs planned link validity.",
    ),
    ("F046", "F069"): (
        SHARED,
        "F069 requires author, datePublished and dateModified, which F046, F048 and F049 "
        "check separately: an Article missing them fails both. Score effect: an F069 "
        "failure whose missing properties are all already failing under F046/F048/F049 "
        "on the same URL counts once, under those features (contribution.UNIT_OVERLAPS); "
        "a missing headline remains F069's own finding.",
    ),
    ("F048", "F069"): (SHARED, "See F046/F069: datePublished is checked by both."),
    ("F049", "F069"): (
        SHARED,
        "See F046/F069: dateModified is checked by both (F049 also accepts a Last-Modified header).",
    ),
    ("F058", "F078"): (
        RELATED,
        "Generic anchor words vs anchor/target term mismatch; F078 is unscored.",
    ),
    ("F060", "F102"): (SAME_DATA, "Text share vs HTML size; both unscored."),
    ("F060", "F108"): (
        RELATED,
        "Text share is an indirect hint at script-built pages; F108 (planned) would measure it directly.",
    ),
    ("F063", "F067"): (
        RELATED,
        "Disjoint by construction: F063 excludes the types F067-F069 cover.",
    ),
    ("F063", "F069"): (
        RELATED,
        "Disjoint by construction: F063 excludes the types F067-F069 cover.",
    ),
}


def catalog_overlaps() -> set[tuple[str, str]]:
    """Pairs the catalog itself declares as neighbours."""
    out = set()
    for f in default_registry().catalog.features:
        for o in f.overlaps:
            out.add(tuple(sorted((f.feature_id, o.feature_id))))
    return out  # type: ignore[return-value]
