"""External sources consulted for the feature audit, with an honest verification state.

Update (2026-11-01): the primary pages of S01, S03-S08, S11-S13 and the new S14 were
fetched and compared with each claim; ``verification`` and ``accessed`` say so per
source. S02, S09 and S10 remain secondary or summary-only.

In the validation session the public web could be reached only through a search tool
that returns summaries; the pages themselves could not be fetched (name resolution was
blocked). Every claim below is therefore *as reported by a search-result summary* and
must be re-checked against the primary page before it is relied on. Nothing is cited
that the search results did not return. ``accessed`` is the date of that search.
"""

from dataclasses import dataclass, replace

ACCESSED = "2026-10-27"
SUMMARY_ONLY = "search-result summary only; primary page not fetched"
SECONDARY_ONLY = "secondary coverage only; primary page not retrieved"
# Final-assignment session: primary pages were fetched (WebFetch) and the claim was
# compared with the page text. Corrections found then are written into ``claim``.
PRIMARY = "primary page fetched 2026-11-01; claim checked against the page text"
REVERIFIED = "2026-11-01"


@dataclass(frozen=True)
class Source:
    source_id: str
    title: str
    publisher: str
    url: str
    claim: str
    verification: str
    accessed: str = ACCESSED


SOURCES: tuple[Source, ...] = (
    Source(
        "S01",
        "Robots meta tag, data-nosnippet, and X-Robots-Tag specifications",
        "Google Search Central",
        "https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag",
        "A noindex rule in a robots meta tag or X-Robots-Tag header keeps a page out of "
        "Google results; the header carries the same rules as the meta tag and suits "
        "non-HTML files; nosnippet and max-snippet:0 stop snippets; the crawler must be "
        "able to fetch the page to see the directive. (The exact full rule list was not "
        "returned.)",
        SUMMARY_ONLY,
    ),
    Source(
        "S02",
        "Googlebot (crawler documentation, file size limit)",
        "Google Search Central",
        "https://developers.google.cn/search/docs/advanced/crawling/googlebot?hl=fa",
        "Googlebot processes only the first 15 MB of an HTML file or supported "
        "text-based file, measured on uncompressed data; crawling stops at the cutoff and "
        "only that portion is considered for indexing. (Localised copy returned; the "
        "current English page was not checked.)",
        SUMMARY_ONLY,
    ),
    Source(
        "S03",
        'How to specify a canonical URL with rel="canonical" and other methods',
        "Google Search Central (older mirror) and web.dev",
        "https://developers.google.com/search/docs/advanced/guidelines/duplicate-content",
        "Specifying a canonical is generally not critical but lets site owners control "
        "the URL shown, consolidate signals and reduce crawl time on duplicates; "
        "robots.txt is not a canonicalisation method; rel=canonical is a hint, not a "
        "directive. (An older mirror was returned; current wording unconfirmed.)",
        SUMMARY_ONLY,
    ),
    Source(
        "S04",
        "RFC 9309: Robots Exclusion Protocol",
        "IETF",
        "https://datatracker.ietf.org/doc/html/rfc9309",
        "If robots.txt is unreachable because of server or network errors it is "
        "undefined and the crawler must assume complete disallow; a 4xx is treated as "
        "no restrictions. (Quoted by a secondary source; the 500 KiB parsing minimum "
        "was not confirmed against the RFC text.)",
        SECONDARY_ONLY,
    ),
    Source(
        "S05",
        "How Google interprets the robots.txt specification",
        "Google Search Central",
        "https://developers.google.com/search/reference/robots_txt",
        "Google enforces a 500 KiB maximum for robots.txt and ignores content beyond "
        "it; on 5xx Google stops crawling for 12 hours, then uses a cached copy for up "
        "to 30 days, then assumes no restrictions (differs from RFC 9309's disallow).",
        SUMMARY_ONLY,
    ),
    Source(
        "S06",
        "General structured data guidelines",
        "Google Search Central",
        "https://developers.google.com/search/docs/appearance/structured-data/sd-policies",
        "Markup must match what users see on the page; JSON-LD is the recommended "
        "format; violating a quality guideline can stop even syntactically correct "
        "markup from showing as a rich result; structured data pages should stay "
        "crawlable.",
        SUMMARY_ONLY,
    ),
    Source(
        "S07",
        "Overview of OpenAI Crawlers",
        "OpenAI",
        "https://developers.openai.com/api/docs/bots",
        "GPTBot (training), OAI-SearchBot (search) and ChatGPT-User (user-triggered "
        "fetches) are controlled by independent robots.txt settings; robots.txt "
        "changes can take about 24 hours to apply; ChatGPT-User fetches are "
        "user-initiated and robots.txt rules may not apply to them.",
        SUMMARY_ONLY,
    ),
    Source(
        "S08",
        "Understand the JavaScript SEO basics",
        "Google Search Central",
        "https://developers.google.com/webmasters/ajax-crawling",
        "Googlebot crawls, queues pages for rendering and then indexes; it does not "
        "render JavaScript for pages blocked by robots.txt; rendering is queued and "
        "can lag. (A legacy-URL copy was returned.)",
        SUMMARY_ONLY,
    ),
    Source(
        "S09",
        "The rise of the AI crawler",
        "Vercel (with MERJ)",
        "https://vercel.com/blog/the-rise-of-the-ai-crawler",
        "In the authors' measurements none of the major AI crawlers (OpenAI, "
        "Anthropic, Meta, ByteDance, Perplexity) rendered JavaScript, although some "
        "downloaded script files; Googlebot-based and Applebot crawlers did render. "
        "A traffic study from one hosting network at one point in time, not a "
        "guarantee about any crawler's current behaviour.",
        SUMMARY_ONLY,
    ),
    Source(
        "S10",
        "Controlling titles and descriptions in Google Search (title links and snippets)",
        "Google Search Central (as reported by Search Engine Land)",
        "https://searchengineland.com/google-publishes-new-help-documents-on-controlling-titles-and-descriptions-in-search-375057",
        "Google derives title links and snippets from several sources, including the "
        "title element and the meta description plus page content; descriptive titles "
        "are advised. Title and description length figures seen in results were not "
        "from Google and are not used.",
        SECONDARY_ONLY,
    ),
    Source(
        "S11",
        "Understanding Success Criterion 1.1.1: Non-text Content",
        "W3C (WCAG 2.1 Understanding document)",
        "https://w3c.github.io/wcag21/understanding/non-text-content.html",
        "Non-text content presented to the user needs a text alternative serving an "
        "equivalent purpose, with exceptions including decoration, which should be "
        "implemented so assistive technology can ignore it. (WCAG 2.1 path returned; "
        "the 2.2 wording was not confirmed.)",
        SUMMARY_ONLY,
    ),
    Source(
        "S12",
        "Build and submit a sitemap",
        "Google Search Central",
        "https://developers.google.com/search/docs/guides/create-URLs",
        "A sitemap file is limited to 50 MB uncompressed or 50,000 URLs, must be "
        "UTF-8, should use absolute URLs and is best placed at the site root.",
        SUMMARY_ONLY,
    ),
    Source(
        "S13",
        "Video (VideoObject, Clip, BroadcastEvent) structured data",
        "Google Search Central",
        "https://developers.google.com/search/docs/appearance/structured-data/video",
        "VideoObject needs name, description, thumbnailUrl and uploadDate for video "
        "rich results. (The property list came from a third-party guide; Google's own "
        "page text was not returned.)",
        SECONDARY_ONLY,
    ),
)

# --- Primary-page re-verification (2026-11-01) --------------------------------------
# Each entry: (url actually fetched, claim as the fetched page states it). The original
# summary-based claims above are kept for history; the shipped values are these.
_REVERIFIED: dict[str, tuple[str, str]] = {
    "S01": (
        "https://developers.google.com/search/reference/robots_meta_tag",
        "noindex: 'Do not show this page, media, or resource in search results.' 'Any rule "
        "that can be used in a robots meta tag can also be specified as an X-Robots-Tag', "
        "recommended for non-HTML resources. nosnippet: no text snippet or video preview; "
        "max-snippet 0 is 'Equivalent to nosnippet'. The settings 'can be read and followed "
        "only if crawlers are allowed to access the pages'. (Page last updated 2026-03-24.)",
    ),
    "S03": (
        "https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls",
        "'it's generally not critical to specify a canonical preference'; reasons: choose "
        "the URL shown in results, consolidate signals, avoid crawling duplicates. 'Don't "
        "use the robots.txt file for canonicalization purposes.' rel=canonical is 'A strong "
        "signal' (the page does not use the word 'hint'); methods 'can stack' and 'none of "
        "them are required'. (Page last updated 2026-07-10.)",
    ),
    "S04": (
        "https://datatracker.ietf.org/doc/html/rfc9309",
        "Section 2.3.1.4: if robots.txt is unreachable due to server or network errors "
        "'the crawler MUST assume complete disallow'. Section 2.3.1.3: 4xx ('unavailable') "
        "means crawlers may access any resources. Section 2.5: 'The parsing limit MUST be "
        "at least 500 kibibytes'.",
    ),
    "S05": (
        "https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt?hl=es-419",
        "Google applies a 500 KiB size limit and ignores content beyond it. On 5xx: stops "
        "crawling for the first 12 hours, then uses the last cached version for up to 30 "
        "days; afterwards, if the site is generally available, behaves as if there were no "
        "robots.txt, otherwise keeps crawling stopped. All 4xx except 429 are treated as "
        "no valid robots.txt. (Spanish-language copy, last updated 2026-10-27.)",
    ),
    "S06": (
        "https://developers.google.com/search/docs/appearance/structured-data/sd-policies",
        "'Your structured data must be a true representation of the page content'; formats "
        "listed as 'JSON-LD (recommended)', Microdata, RDFa; 'Violating a quality guideline "
        "can prevent syntactically correct structured data from being displayed as a rich "
        "result'; 'Don't block your structured data pages to Googlebot using robots.txt.' "
        "(Page last updated 2026-07-10.)",
    ),
    "S07": (
        "https://developers.openai.com/docs/gptbot",
        "GPTBot: training of generative AI foundation models; OAI-SearchBot: surfacing "
        "websites in ChatGPT search; 'Each setting is independent of the others'; search "
        "changes can take '~24 hours'; for ChatGPT-User 'robots.txt rules may not apply' "
        "because actions are user-initiated.",
    ),
    "S08": (
        "https://developers.google.com/webmasters/ajax-crawling",
        "Google processes JavaScript web apps in three phases (crawling, rendering, "
        "indexing); 'Google Search won't render JavaScript from blocked files or on blocked "
        "pages'; a page may wait in the render queue 'a few seconds, but it can take longer'. "
        "(Page last updated 2026-03-04.)",
    ),
    "S11": (
        "https://www.w3.org/WAI/WCAG21/Understanding/non-text-content",
        "SC 1.1.1: 'All non-text content that is presented to the user has a text "
        "alternative that serves the equivalent purpose', except that pure decoration "
        "'is implemented in a way that it can be ignored by assistive technology.'",
    ),
    "S12": (
        "https://developers.google.com/search/docs/guides/create-URLs",
        "'All formats limit a single sitemap to 50MB (uncompressed) or 50,000 URLs'; must be "
        "UTF-8; use fully-qualified absolute URLs; posting at the site root is recommended. "
        "(Page last updated 2026-07-08.)",
    ),
    "S13": (
        "https://developers.google.com/search/docs/appearance/structured-data/video?hl=de",
        "CORRECTION: Google lists name, thumbnailUrl and uploadDate as the required "
        "VideoObject properties for video rich results; description is not in the required "
        "list on the fetched (German, truncated) copy. Geoptimiser's F088 list adds "
        "description as project policy (FeatureConfig.entity_properties).",
    ),
}
SOURCES = tuple(
    replace(s, url=_REVERIFIED[s.source_id][0], claim=_REVERIFIED[s.source_id][1],
            verification=PRIMARY, accessed=REVERIFIED)
    if s.source_id in _REVERIFIED else s
    for s in SOURCES
) + (
    Source(
        "S14",
        "RFC 6797: HTTP Strict Transport Security (HSTS)",
        "IETF",
        "https://datatracker.ietf.org/doc/rfc6797/",
        "Section 6.1.1: 'The REQUIRED \"max-age\" directive specifies the number of "
        "seconds'; max-age=0 'signals the UA to cease regarding the host as a Known HSTS "
        "Host'. Section 6.1: 'All directives MUST appear only once'. Section 8.1: an STS "
        "header received over insecure transport MUST be ignored.",
        PRIMARY,
        REVERIFIED,
    ),
)  # fmt: skip

# Named only as candidates for a later, primary-source review. Nothing is claimed from
# them in this audit.
UNREVIEWED_CANDIDATES: tuple[str, ...] = (
    "WHATWG HTML Standard (title, lang, meta charset, base, noscript, headings)",
    "RFC 5646 / BCP 47 (language tags)",
    "RFC 9110 and RFC 9111 (HTTP semantics, caching, validators)",
    "WAI-ARIA 1.2 and ARIA in HTML (landmark roles)",
    "WCAG 2.2 success criteria 1.2.2, 1.3.1, 1.4.4, 2.4.4, 2.4.6",
    "schema.org type definitions (Article, Product, Offer, Organization, VideoObject)",
    "Google image SEO and Article/Product structured-data documentation",
    "Anthropic, Perplexity and Google-Extended crawler documentation",
)


def by_id() -> dict[str, Source]:
    return {s.source_id: s for s in SOURCES}
