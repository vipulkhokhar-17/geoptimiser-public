"""Shared state for one audit run: inputs, configuration and cross-page indexes."""

import hashlib
import re
from collections import defaultdict
from functools import cached_property
from typing import Any

from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.evidence import link_list_incomplete
from geoptimiser.features.inputs import AuditInputs, PageContext, url_key

_STOPWORDS = frozenset(
    "a an and are as at be but by can for from has have how if in into is it its "
    "of on or our that the their them then there these they this to was we were "
    "what when where which who why will with you your not all any more most".split()
)
STOPWORDS = _STOPWORDS  # public alias for retrieval tokenisation
_TOKEN = re.compile(r"[a-z0-9]{3,}")


def norm(value: str) -> str:
    """Lower-case with collapsed whitespace, for equality comparisons."""
    return " ".join(value.lower().split())


def terms(value: str) -> set[str]:
    """Content terms: lower-case alphanumeric tokens, English stopwords removed."""
    return {t for t in _TOKEN.findall(value.lower()) if t not in _STOPWORDS}


def text_hash(text: str) -> str:
    return hashlib.sha256(norm(text).encode("utf-8")).hexdigest()


def has_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


class Ctx:
    """What a check may consult besides the page it is judging."""

    def __init__(self, inputs: AuditInputs, config: FeatureConfig) -> None:
        self.inputs = inputs
        self.config = config

    @property
    def graph(self):  # type: ignore[no-untyped-def]
        return self.inputs.graph

    def page_for(self, url: str) -> PageContext | None:
        """The crawled page a URL resolves to (following recorded redirects)."""
        node = self.graph.alias.get(url_key(url))
        return self.graph.nodes.get(node) if node else None

    @cached_property
    def uncertain_link_sources(self) -> tuple[PageContext, ...]:
        """Pages whose outgoing links are not fully known (cut, failed or capped).

        A page that no *read* link points to may still be linked from one of these,
        so "no incoming links" is not concluded while any exist.
        """
        return tuple(p for p in self.inputs.pages if link_list_incomplete(p))

    @cached_property
    def title_index(self) -> dict[str, list[PageContext]]:
        return self._index(lambda d: d.title)

    @cached_property
    def description_index(self) -> dict[str, list[PageContext]]:
        return self._index(lambda d: d.meta_description)

    @cached_property
    def text_hash_index(self) -> dict[str, list[PageContext]]:
        index: dict[str, list[PageContext]] = defaultdict(list)
        for page in self.inputs.pages:
            doc = page.document
            if doc and len(norm(doc.text)) >= self.config.duplicate_min_text_chars:
                index[text_hash(doc.text)].append(page)
        return dict(index)

    def _index(self, field) -> dict[str, list[PageContext]]:  # type: ignore[no-untyped-def]
        index: dict[str, list[PageContext]] = defaultdict(list)
        for page in self.inputs.pages:
            value = field(page.document) if page.document else None
            if value and value.strip():
                index[norm(value)].append(page)
        return dict(index)
