"""Tokenisation shared by the lexical index, the test embedder and the reranker."""

import re

from pydantic import Field

from geoptimiser.features.context import STOPWORDS
from geoptimiser.schemas import SchemaModel

_TOKEN = re.compile(r"[a-z0-9]+")


class TokenizerConfig(SchemaModel):
    remove_stopwords: bool = True
    min_token_len: int = Field(default=2, ge=1, le=10)


def tokenize(text: str, config: TokenizerConfig | None = None) -> list[str]:
    """Lower-case alphanumeric tokens, in order, with repeats kept."""
    config = config or TokenizerConfig()
    return [
        t
        for t in _TOKEN.findall(text.lower())
        if len(t) >= config.min_token_len
        and not (config.remove_stopwords and t in STOPWORDS)
    ]
