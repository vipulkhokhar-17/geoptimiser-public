"""How much a result may claim when the evidence behind it is incomplete.

A check reads one extracted document. That document can be incomplete for reasons that
are properties of the *measurement*, not of the website:

* the stored response was cut at the crawl size limit (``source_truncated``);
* an extraction limit stopped one field early (``truncated_fields``);
* the response was a bot-challenge page, not the intended page.

Each content check declares, in ``POLICIES``, what an incomplete document can still
prove. ``apply_evidence_policy`` then turns any result the evidence cannot support
into ``not_measured`` with an explanation that names the real limitation. Results the
evidence does support are kept, so a truncated page can still produce valid findings.

Policy kinds (what remains conclusive when the document is incomplete):

``head``       head metadata (title, description, canonical, robots, ...): everything
               once the parser saw the end of ``<head>``, otherwise only a ``pass``.
``head_violation``  head metadata where a *restriction* is what matters (robots, snippet
               directives): a seen restriction is conclusive; "none" only once the
               head was fully read.
``presence``   "is X there?": a ``pass`` (X was seen) is conclusive; a missing X may
               lie beyond the cut.
``violation``  "is anything wrong?": a ``fail`` (a violation was seen) is conclusive;
               a ``pass`` only covers the part that was read.
``first``      the answer depends on the first item only, so it is conclusive once an
               item was seen; "no items" is not.
``complete``   the result needs the whole document (ratios, totals, hashes).

Checks that read only headers, the fetch record or the cross-page link graph are
not listed here; the graph checks apply the same idea to link sources themselves.
"""

from dataclasses import dataclass, replace
from typing import Literal

from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import Outcome
from geoptimiser.schemas import PageDocument

Kind = Literal["head", "head_violation", "presence", "violation", "first", "complete"]


@dataclass(frozen=True)
class EvidencePolicy:
    kind: Kind
    fields: tuple[str, ...] = ()


_P = EvidencePolicy
POLICIES: dict[str, EvidencePolicy] = {
    "F002": _P("presence", ("anchors", "links")),
    "F005": _P("head_violation"),
    "F011": _P("head"),
    "F012": _P("head"),
    "F013": _P("head"),
    "F014": _P("complete", ("text",)),
    "F020": _P("violation", ("links",)),
    "F021": _P("head", ("title",)),
    "F022": _P("head", ("title",)),
    "F023": _P("head", ("title",)),
    "F024": _P("head"),
    "F025": _P("head"),
    "F026": _P("presence", ("text",)),
    "F027": _P("head"),
    "F028": _P("head"),
    "F029": _P("head"),
    "F030": _P("head_violation"),
    "F031": _P("complete", ("title", "headings", "text")),
    "F035": _P("violation", ("headings",)),
    "F036": _P("violation", ("headings",)),
    "F040": _P("presence", ("headings", "structured_data")),
    "F041": _P("presence", ("text", "links")),
    "F046": _P("violation", ("structured_data",)),
    "F047": _P("presence", ("structured_data",)),
    "F048": _P("presence", ("structured_data",)),
    "F049": _P("presence", ("structured_data",)),
    "F050": _P("violation", ("structured_data",)),
    "F051": _P("presence", ("text",)),
    "F052": _P("presence", ("landmarks",)),
    "F053": _P("complete", ("text", "landmarks")),
    "F054": _P("complete", ("text",)),
    "F055": _P("presence", ("landmarks",)),
    "F056": _P("violation", ("tables",)),
    "F057": _P("complete", ("lists", "text")),
    "F058": _P("violation", ("anchors",)),
    "F059": _P("violation", ("landmarks",)),
    "F060": _P("complete", ("text",)),
    "F062": _P("presence", ("structured_data",)),
    "F063": _P("violation", ("structured_data",)),
    "F064": _P("violation", ("structured_data",)),
    "F067": _P("violation", ("structured_data",)),
    "F068": _P("violation", ("structured_data",)),
    "F069": _P("violation", ("structured_data",)),
    "F070": _P("presence", ("text", "headings", "title", "structured_data")),
    "F071": _P("complete", ("text", "links")),
    "F073": _P("complete", ("links",)),
    "F077": _P("presence", ("anchors",)),
    "F078": _P("violation", ("anchors",)),
    "F081": _P("violation", ("images",)),
    "F082": _P("violation", ("images",)),
    "F083": _P("violation", ("images",)),
    "F084": _P("first", ("images",)),
    "F086": _P("presence", ("media", "text")),
    "F087": _P("violation", ("media",)),
    "F088": _P("presence", ("media", "structured_data")),
    "F089": _P("presence", ("media", "text")),
    "F091": _P("violation", ("headings", "text")),
    "F092": _P("violation", ("headings", "text")),
    "F094": _P("presence", ("lists", "text", "headings")),
    "F095": _P("presence", ("tables", "headings")),
}
# Content checks that handle their evidence themselves, with the reason.
SELF_MANAGED: dict[str, str] = {
    "F061": "distinguishes truncated, skipped and invalid JSON-LD blocks by cause",
    "F009": "link-graph check: uses ctx.uncertain_link_sources",
    "F010": "link-graph check: uses ctx.uncertain_link_sources",
    "F017": "link-graph check: judges the links of one page it read",
    "F072": "link-graph check: uses ctx.uncertain_link_sources",
    "F079": "site-level: aggregates only links that were read",
    "F066": "site-level: compares only entities that were read",
    "F080": "site-level: compares only titles that were read",
}
# Self-managed content checks that still must not run on an interstitial page.
INTERSTITIAL_GUARDED = frozenset(POLICIES) | {"F061"}
_CONCLUSIVE: dict[Kind, frozenset[str]] = {
    "head": frozenset({"pass"}),
    "head_violation": frozenset({"fail", "warning"}),
    "presence": frozenset({"pass"}),
    "violation": frozenset({"fail", "warning"}),
    "first": frozenset({"pass", "fail", "warning"}),
    "complete": frozenset(),
}


@dataclass(frozen=True)
class PageState:
    """What is known about the response behind a page, independent of any feature."""

    truncated: bool
    interstitial: str | None
    client_rendered: str | None


def interstitial_marker(doc: PageDocument, config: FeatureConfig) -> str | None:
    """The marker phrase if ``doc`` looks like a bot-challenge or consent page."""
    if len(doc.text) > config.interstitial_max_text_chars:
        return None
    haystack = f"{(doc.title or '').lower()} {doc.text[:400].lower()}"
    return next((m for m in config.interstitial_markers if m in haystack), None)


def client_rendered_evidence(doc: PageDocument, config: FeatureConfig) -> str | None:
    """Why the initial HTML looks like a client-rendered shell, if it does.

    Requires almost no extracted text *and* a concrete sign of script-built content
    (an app mount point, a noscript "enable JavaScript" notice, or two or more scripts).
    This describes the HTML that was fetched; it does not say what a browser shows.
    """
    signals = doc.render_signals
    if signals is None or len(doc.text) >= config.min_extractable_chars:
        return None
    reasons = []
    if signals.mount_points:
        reasons.append(f"app mount point {', '.join(signals.mount_points)}")
    if signals.noscript_notice:
        reasons.append(f'noscript notice "{signals.noscript_notice}"')
    if signals.script_tags >= 2:
        reasons.append(f"{signals.script_tags} script tags")
    if not reasons:
        return None
    return f"{len(doc.text)} characters of text in the initial HTML; " + "; ".join(
        reasons
    )


def page_state(page: PageContext, config: FeatureConfig) -> PageState:
    doc = page.document
    if doc is None:
        return PageState(False, None, None)
    return PageState(
        truncated=doc.source_truncated,
        interstitial=interstitial_marker(doc, config),
        client_rendered=client_rendered_evidence(doc, config),
    )


def link_list_incomplete(page: PageContext) -> bool:
    """True if the page's outgoing links are not fully known."""
    if page.fetch.outcome != "success" or page.fetch.body is None:
        return False  # nothing was served that could hold links
    doc = page.document
    return doc is None or doc.source_truncated or "links" in doc.truncated_fields


def _incomplete_reason(
    policy: EvidencePolicy, doc: PageDocument, page: PageContext
) -> str | None:
    cut = [f for f in policy.fields if f in doc.truncated_fields]
    if doc.source_truncated:
        head_known = doc.head_complete is True
        if policy.kind not in ("head", "head_violation") or not head_known:
            size = page.fetch.body.size_bytes if page.fetch.body else 0
            return (
                f"the stored response was truncated at {size:,} bytes (crawl size "
                "limit), so content after the cut was not inspected"
            )
    if cut:
        return (
            f"extraction stopped at its limit for {', '.join(cut)}, so more existed "
            "than was inspected"
        )
    return None


def apply_evidence_policy(
    feature_id: str, outcome: Outcome, page: PageContext, config: FeatureConfig
) -> Outcome:
    """Downgrade ``outcome`` to ``not_measured`` if its evidence cannot support it."""
    doc = page.document
    if doc is None or feature_id not in INTERSTITIAL_GUARDED:
        return outcome
    if outcome.status == "error":
        return outcome
    marker = interstitial_marker(doc, config)
    if marker is not None:
        return Outcome(
            "not_measured",
            f"Inconclusive: the response looks like an interstitial or bot-challenge "
            f'page (matched "{marker}"), not the intended page, so this content '
            "check was not run.",
            limitations=("The fetched page was not the intended content.",),
        )
    policy = POLICIES.get(feature_id)
    if policy is None:  # self-managed (F061)
        return outcome
    reason = _incomplete_reason(policy, doc, page)
    if reason is None:
        return _note_shell(policy, outcome, doc, config)
    if outcome.status in _CONCLUSIVE[policy.kind]:
        return replace(
            outcome,
            limitations=(
                *outcome.limitations,
                f"Partial evidence: {reason}; this result covers only what was read.",
            ),
        )
    detail = outcome.explanation.rstrip(".")
    return Outcome(
        "not_measured",
        f"Inconclusive: {reason}. Without that evidence the result "
        f'"{detail}" is not concluded.',
        limitations=(f"Not concluded because {reason}.",),
    )


def _note_shell(
    policy: EvidencePolicy, outcome: Outcome, doc: PageDocument, config: FeatureConfig
) -> Outcome:
    """Say so when an absence-based failure is read from a client-rendered shell."""
    if outcome.status != "fail" or policy.kind not in ("head", "presence"):
        return outcome
    evidence = client_rendered_evidence(doc, config)
    if evidence is None:
        return outcome
    return replace(
        outcome,
        limitations=(
            *outcome.limitations,
            f"The initial HTML looks client-rendered ({evidence}). The audit does not "
            "execute JavaScript, so content added by scripts was not evaluated; this "
            "result describes the HTML as fetched.",
        ),
    )
