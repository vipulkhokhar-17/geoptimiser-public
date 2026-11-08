"""Category G: structured data and entity semantics (JSON-LD and microdata types)."""

from typing import Any

from geoptimiser.features.checks._common import entities, obs, types_of
from geoptimiser.features.context import Ctx, has_value, norm
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import (
    Obs,
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
)
from geoptimiser.features.registry import Unit, check


def _missing(entity: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    return [p for p in required if not has_value(entity.get(p))]


def _completeness(
    page: PageContext,
    ctx: Ctx,
    wanted: set[str],
    label: str,
    found: list[dict[str, Any]],
) -> Outcome:
    """Shared completeness test: every entity must carry its configured properties."""
    properties = ctx.config.entity_properties
    problems: list[str] = []
    for entity in found:
        for type_name in types_of(entity):
            if type_name in wanted and type_name in properties:
                missing = _missing(entity, properties[type_name])
                if missing:
                    problems.append(f"{type_name} lacks {', '.join(missing)}")
                break
    if not found:
        return not_applicable(f"No {label} entity on the page.")
    if not problems:
        return passed(
            f"All {len(found)} {label} entities have the configured properties.", [], []
        )
    return failed(
        "; ".join(problems[:5]) + ".",
        (obs(page, "; ".join(problems[:3])),),
        problems,
        [],
    )


def _of_types(page: PageContext, wanted: set[str]) -> list[dict[str, Any]]:
    assert page.document is not None
    return [e for e in entities(page.document) if wanted & set(types_of(e))]


@check("F061", version=2)
def jsonld_validity(page: PageContext, ctx: Ctx) -> Outcome:
    """Separate a site defect from a measurement limit, block by block.

    A block that closed but is not valid JSON, or that never closed in a *complete*
    document, is a defect. A block cut off by a truncated response, or skipped by an
    extraction size limit, is a limit of this measurement: not_measured, and never a
    request to "fix the JSON".
    """
    doc = page.document
    assert doc is not None
    errors, causes, cut = (
        doc.structured_data_errors,
        doc.structured_data_error_causes,
        doc.source_truncated,
    )
    skipped = "structured_data" in doc.truncated_fields
    if not doc.structured_data and errors == 0:
        if cut or skipped:
            return not_measured(
                "No JSON-LD was found in the part of the page that was read, but the "
                "response was truncated or a limit was reached, so JSON-LD may exist "
                "beyond it."
            )
        return not_applicable("The page has no JSON-LD to validate.")
    if errors and not causes:  # recorded by an older extractor: cause unknown
        if cut:
            return not_measured(
                f"{errors} JSON-LD block(s) did not parse, but the cause was not "
                "recorded and the response was truncated, so a cut block cannot be "
                "ruled out. Re-run extraction to record causes."
            )
        causes = {"syntax_error": errors}
    broken = causes.get("syntax_error", 0) + (
        0 if cut else causes.get("unterminated", 0)
    )
    cut_blocks = causes.get("unterminated", 0) if cut else 0
    skipped_blocks = causes.get("size_limit", 0) + causes.get("nesting_limit", 0)
    if broken:
        notes = []
        if cut_blocks:
            notes.append(
                f"{cut_blocks} more block(s) were cut by the truncated response"
            )
        if skipped_blocks:
            notes.append(f"{skipped_blocks} block(s) were skipped by a size limit")
        return failed(
            f"{broken} JSON-LD block(s) could not be parsed (invalid JSON or a block "
            "that never closes)." + (" " + "; ".join(notes) + "." if notes else ""),
            (
                obs(
                    page,
                    f"{broken} unparseable JSON-LD block(s); "
                    f"{len(doc.structured_data)} parsed",
                ),
            ),
            broken,
            0,
        )
    if cut_blocks or skipped_blocks:
        reasons = []
        if cut_blocks:
            reasons.append(
                f"{cut_blocks} block(s) were cut off because the stored response was "
                "truncated (an incomplete input, not evidence of invalid JSON)"
            )
        if skipped_blocks:
            reasons.append(
                f"{skipped_blocks} block(s) were skipped because they exceeded an "
                "extraction size/nesting limit (an incomplete input, not evidence of invalid JSON)"
            )
        return not_measured(
            "Inconclusive: " + "; ".join(reasons) + ". The other blocks parsed."
        )
    if cut or skipped:
        return not_measured(
            f"{len(doc.structured_data)} JSON-LD block(s) parsed, but the response "
            "was truncated or a limit was reached, so later blocks were not read."
        )
    return passed(f"{len(doc.structured_data)} JSON-LD block(s) parsed.", 0, 0)


@check("F062")
def type_coverage(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if doc.structured_data_types:
        return passed(
            f"{len(doc.structured_data_types)} type(s) declared.",
            list(doc.structured_data_types),
            ">= 1 type",
        )
    return failed(
        "No schema.org type is declared.",
        (obs(page, "no JSON-LD @type or microdata itemtype"),),
        [],
        ">= 1 type",
    )


@check("F063")
def property_completeness(page: PageContext, ctx: Ctx) -> Outcome:
    specific = {"Product", "Offer", *ctx.config.article_types}  # covered by F067-F069
    generic = {t for t in ctx.config.entity_properties if t not in specific}
    return _completeness(page, ctx, generic, "configured", _of_types(page, generic))


@check("F064")
def entity_identifiers(page: PageContext, ctx: Ctx) -> Outcome:
    found = _of_types(page, {"Organization", "Person"})
    if not found:
        return not_applicable("No Organization or Person entity on the page.")
    bare = [
        e
        for e in found
        if not has_value(e.get("@id")) and not has_value(e.get("sameAs"))
    ]
    if not bare:
        return passed("Every Organization/Person has an @id or sameAs.", [], [])
    names = [str(e.get("name", "(unnamed)")) for e in bare]
    return failed(
        f"{len(bare)} entity(ies) have neither @id nor sameAs.",
        (obs(page, f"no identifier: {', '.join(names[:3])}"),),
        names,
        [],
    )


@check("F066", scope="site", requires="none")
def organization_consistency(ctx: Ctx) -> Outcome | list[Unit]:
    names: dict[str, list[tuple[PageContext, str]]] = {}
    for page in ctx.inputs.pages:
        if page.document is None:
            continue
        for entity in entities(page.document):
            name = entity.get("name")
            if (
                "Organization" in types_of(entity)
                and isinstance(name, str)
                and name.strip()
            ):
                names.setdefault(norm(name), []).append((page, name.strip()))
    pages_with_org = {p.key for group in names.values() for p, _ in group}
    if len(pages_with_org) < 2:
        return not_applicable("Fewer than two pages declare a named Organization.")
    if len(names) == 1:
        return passed(
            f"{len(pages_with_org)} pages agree on one Organization name.",
            list(names),
            "one name",
        )
    evidence = tuple(
        Obs(p.url, f'Organization name "{n}"')
        for group in names.values()
        for p, n in group[:2]
    )
    return failed(
        f"{len(names)} different Organization names across pages.",
        evidence,
        [group[0][1] for group in names.values()],
        "one name",
    )


@check("F067")
def product_completeness(page: PageContext, ctx: Ctx) -> Outcome:
    return _completeness(
        page, ctx, {"Product"}, "Product", _of_types(page, {"Product"})
    )


@check("F068")
def offer_completeness(page: PageContext, ctx: Ctx) -> Outcome:
    offers = _of_types(page, {"Offer"})
    for product in _of_types(page, {"Product"}):
        nested = product.get("offers")
        for item in nested if isinstance(nested, list) else [nested]:
            if isinstance(item, dict):
                offers.append({**item, "@type": item.get("@type", "Offer")})
    return _completeness(page, ctx, {"Offer"}, "Offer", offers)


@check("F069")
def article_completeness(page: PageContext, ctx: Ctx) -> Outcome:
    wanted = set(ctx.config.article_types)
    return _completeness(page, ctx, wanted, "Article", _of_types(page, wanted))


_MAX_F070_CLAIMS = 200


@check("F070", version=2)
def visible_consistency(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    visible = norm(
        " ".join([doc.title or "", *(h.text for h in doc.headings), doc.text])
    )
    claims = [
        (e, v)
        for e in entities(doc)
        for key in ("headline", "name")
        if isinstance((v := e.get(key)), str)
        and v.strip()
        and (key == "headline" or "Product" in types_of(e))
    ]
    if not claims:
        return not_applicable("No headline or Product name in structured data.")
    # Each distinct value is searched once, and at most _MAX_F070_CLAIMS of them: the
    # search is a substring scan of the visible text, so an uncapped, page-controlled
    # number of JSON-LD entities made this check cost entities x text with no deadline
    # (security audit run 1). Beyond the cap the check can still fail, but cannot pass.
    distinct = list(dict.fromkeys(v for _, v in claims))
    examined = distinct[:_MAX_F070_CLAIMS]
    absent = [v for v in examined if norm(v) not in visible]
    if not absent:
        if len(distinct) > len(examined):
            return not_measured(
                f"Only the first {len(examined)} of {len(distinct)} distinct structured-data "
                "names were compared with the visible content; all of those appear, but "
                "the rest were not checked."
            )
        return passed("Structured-data names appear in the visible content.", [], [])
    return failed(
        f"{len(absent)} structured-data value(s) do not appear in the visible content"
        + (
            f" (first {len(examined)} of {len(distinct)} distinct values compared)."
            if len(distinct) > len(examined)
            else "."
        ),
        tuple(
            obs(page, f'structured data says "{a}"; not found on the page')
            for a in absent[:5]
        ),
        absent[:50],
        [],
    )
