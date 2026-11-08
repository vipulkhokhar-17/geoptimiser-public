"""Importing this package registers every implemented check."""

from geoptimiser.features.checks import (  # noqa: F401
    content,
    crawl,
    delivery,
    linking,
    metadata,
    structure,
    structured,
    trust,
    urls,
)
