"""Stage 01: safe, bounded website crawler producing ``FetchRecord`` artifacts."""

from geoptimiser.crawler.artifacts import ArtifactWriter, read_fetches
from geoptimiser.crawler.config import CrawlConfig
from geoptimiser.crawler.crawl import Crawler, CrawlResult, SkippedUrl
from geoptimiser.crawler.fetcher import FetchResult, SafeFetcher
from geoptimiser.crawler.netguard import PolicyViolation, is_public_address
from geoptimiser.crawler.storage import BodyStore, LocalBodyStore, StorageError

__all__ = [
    "ArtifactWriter",
    "BodyStore",
    "CrawlConfig",
    "CrawlResult",
    "Crawler",
    "FetchResult",
    "LocalBodyStore",
    "PolicyViolation",
    "SafeFetcher",
    "SkippedUrl",
    "StorageError",
    "is_public_address",
    "read_fetches",
]
