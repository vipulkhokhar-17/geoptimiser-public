"""Structure collected while parsing: images, anchors, landmarks, tables, lists, media.

``RichState`` is driven by the parser's tag and text events and owns everything about
these elements. It never fetches or evaluates anything; every collection is bounded by
``ExtractionConfig`` and a cut is reported in ``truncated``. Elements that are hidden,
inert (``noscript``/``template``) or foreign (``svg``/``math``) are not collected.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from geoptimiser.extraction.config import ExtractionConfig

_SEMANTIC = frozenset(
    "main article section nav header footer aside figure figcaption time address "
    "details summary".split()
)
_LANDMARK_ROLES = frozenset(
    "main navigation banner contentinfo complementary region search article".split()
)
_BOILERPLATE_ROLES = frozenset({"navigation", "complementary", "banner", "contentinfo"})
_SECTIONING = frozenset({"article", "section", "main"})
_DIMENSION = re.compile(r"^\s*(\d{1,6})(?:\.\d+)?(?:px)?\s*$")
_CAPTION_KINDS = frozenset({"captions", "subtitles", ""})


def squash(value: str) -> str:
    return " ".join(value.split())


@dataclass
class _Extra:
    """What one open element contributed, so closing it can undo exactly that."""

    kind: str | None = (
        None  # anchor/table/caption/tr/cell/list/item/figure/figcaption/media
    )
    ref: dict[str, Any] | None = None
    boiler: bool = False
    main: bool = False
    sectioning: bool = False
    landmark: dict[str, Any] | None = None


class RichState:
    def __init__(self, cfg: ExtractionConfig, page_host: str, resolve: Any) -> None:
        self._cfg = cfg
        self._host = (page_host or "").lower().removeprefix("www.")
        self._resolve = resolve  # str -> absolute http(s) URL or None (base-aware)
        self.truncated: set[str] = set()
        self.images: list[dict[str, Any]] = []
        self.anchors: list[dict[str, Any]] = []
        self.landmarks: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.lists: list[dict[str, Any]] = []
        self.media: list[dict[str, Any]] = []
        self.semantic_counts: Counter[str] = Counter()
        self.boilerplate_chars = 0
        self.main_chars = 0
        self.hidden_chars = 0
        self._boiler = 0
        self._main = 0
        self._sectioning = 0
        self._open_landmarks: list[dict[str, Any]] = []
        self._anchor: dict[str, Any] | None = None
        self._anchor_keys: set[tuple[Any, ...]] = set()
        self._tables: list[dict[str, Any]] = []
        self._lists: list[dict[str, Any]] = []
        self._figures: list[dict[str, Any]] = []
        self._caption: dict[str, Any] | None = None  # table caption or figcaption
        self._media: dict[str, Any] | None = None
        self._tail = ""
        self._pending: list[dict[str, Any]] = []

    # -- events from the parser ----------

    def on_start(
        self, tag: str, attr: dict[str, str], live: bool, hidden: bool
    ) -> _Extra | None:
        """An element opened (non-void). Returns what to hand back when it closes."""
        if not live or hidden:
            return None
        role = attr.get("role", "").strip().lower().split(" ")[0]
        extra = _Extra()
        if tag in _SEMANTIC:
            self.semantic_counts[tag] += 1
        page_level = self._sectioning == 0
        if (
            tag in ("nav", "aside")
            or role in _BOILERPLATE_ROLES
            or (tag in ("header", "footer") and page_level)
        ):
            extra.boiler = True
            self._boiler += 1
        if tag in ("main", "article") or role in ("main", "article"):
            extra.main = True
            self._main += 1
        if tag in _SECTIONING:
            extra.sectioning = True
            self._sectioning += 1
        self._landmark(tag, attr, role, page_level, extra)
        if tag == "a" and "href" in attr:
            self._open_anchor(attr, extra)
        elif tag == "figure":
            figure: dict[str, Any] = {"images": [], "caption": None}
            self._figures.append(figure)
            extra.kind, extra.ref = "figure", figure
        elif tag == "figcaption" and self._figures:
            self._start_caption(extra, "figcaption", self._figures[-1])
        elif tag == "table":
            self._open_table(attr, role, extra)
        elif tag == "caption" and self._tables:
            self._start_caption(extra, "caption", self._tables[-1])
        elif tag == "tr" and self._tables:
            self._start_row(self._tables[-1])
            extra.kind, extra.ref = "tr", self._tables[-1]["row"]
        elif tag in ("td", "th") and self._tables:
            self._start_cell(self._tables[-1], tag == "th")
            extra.kind, extra.ref = "cell", self._tables[-1]["cell"]
        elif tag in ("ul", "ol", "dl"):
            self._open_list(tag, extra)
        elif tag in ("li", "dt") and self._lists:
            self._start_item(self._lists[-1], tag)
            extra.kind, extra.ref = "item", self._lists[-1]["item"]
        elif tag in ("video", "audio"):
            self._open_media(tag, attr, extra)
        elif tag == "iframe":
            self._iframe(attr)
        return extra

    def on_void(self, tag: str, attr: dict[str, str], live: bool, hidden: bool) -> None:
        """A void element (``img``, ``source``, ``track``)."""
        if not live or hidden:
            return
        if tag == "img":
            self._image(attr)
        elif tag == "source" and self._media is not None and self._media["src"] is None:
            self._media["src"] = self._url(attr.get("src", ""))
        elif tag == "track" and self._media is not None:
            kind = attr.get("kind", "").strip().lower()
            if self._media["kind"] == "video" and kind in _CAPTION_KINDS:
                self._media["has_captions"] = True

    def on_end(self, popped: list[_Extra | None]) -> None:
        """Elements closed, outermost first (as removed from the parser's stack)."""
        for extra in reversed(popped):
            if extra is None:
                continue
            if extra.kind == "anchor":
                self._finish_anchor(extra.ref)
            elif extra.kind in ("caption", "figcaption"):
                self._finish_caption(extra.ref)
            elif extra.kind == "cell":
                self._finish_cell(extra.ref)
            elif extra.kind == "tr":
                self._finish_row(extra.ref)
            elif extra.kind == "table":
                self._finish_table(extra.ref)
            elif extra.kind == "item":
                self._finish_item(extra.ref)
            elif extra.kind == "list":
                self._finish_list(extra.ref)
            elif extra.kind == "figure":
                self._finish_figure(extra.ref)
            elif extra.kind == "media":
                self._finish_media(extra.ref)
            if extra.landmark is not None and extra.landmark in self._open_landmarks:
                self._open_landmarks.remove(extra.landmark)
            self._boiler -= extra.boiler
            self._main -= extra.main
            self._sectioning -= extra.sectioning

    def on_text(self, data: str) -> None:
        """Visible text (the same text the page's ``text`` field is built from)."""
        flat = data.translate({10: 32, 13: 32, 9: 32})
        chunk = squash(flat)
        self._tail = (self._tail + flat)[-4 * self._cfg.context_chars :]
        for pending in self._pending:
            room = self._cfg.context_chars - len(pending["after"])
            pending["after"] += flat[:room]
        for pending in self._pending:
            if len(pending["after"]) >= self._cfg.context_chars:
                pending["rec"]["context_after"] = squash(pending["after"])
        self._pending = [
            p for p in self._pending if len(p["after"]) < self._cfg.context_chars
        ]
        if not chunk:
            return
        if self._boiler > 0:
            self.boilerplate_chars += len(chunk)
        if self._main > 0:
            self.main_chars += len(chunk)
        for landmark in self._open_landmarks:
            landmark["text_chars"] += len(chunk)
        self._collect(self._anchor, flat, self._cfg.max_anchor_chars)
        if self._caption is not None:
            self._collect(self._caption, flat)
        if self._tables and self._tables[-1]["cell"] is not None:
            self._collect(self._tables[-1]["cell"], flat, self._cfg.max_cell_chars)
        if self._lists and self._lists[-1]["item"] is not None:
            self._collect(self._lists[-1]["item"], flat, self._cfg.max_cell_chars)

    def on_break(self) -> None:
        """A block boundary: keeps neighbouring blocks' text apart in the context."""
        self._tail = (self._tail + " ")[-4 * self._cfg.context_chars :]
        for pending in self._pending:
            if len(pending["after"]) < self._cfg.context_chars:
                pending["after"] += " "

    def on_hidden(self, data: str) -> None:
        self.hidden_chars += len(squash(data))

    def finish(self) -> None:
        """Close whatever the document left open."""
        self._finish_anchor(self._anchor)
        while self._tables:
            table = self._tables[-1]
            self._finish_cell(table["cell"])
            self._finish_row(table["row"])
            self._finish_table(table)
        while self._lists:
            self._finish_list(self._lists[-1])
        while self._figures:
            self._finish_figure(self._figures[-1])
        if self._media is not None:
            self._finish_media(self._media)
        for pending in self._pending:
            pending["rec"]["context_after"] = squash(pending["after"])
        self._pending = []

    # -- helpers ----------

    @staticmethod
    def _collect(holder: dict[str, Any] | None, flat: str, limit: int = 300) -> None:
        if holder is None:
            return
        used = holder.setdefault("used", 0)
        if used < limit:
            holder.setdefault("parts", []).append(flat[: limit - used])
            holder["used"] = used + len(flat)

    def _url(self, raw: str) -> str | None:
        raw = raw.strip()
        if raw.lower().startswith("data:"):
            return "data:"
        if not raw or len(raw) > self._cfg.max_attr_chars:
            return None
        return self._resolve(raw)

    def _internal(self, host: str) -> bool:
        host = host.lower().removeprefix("www.")
        return bool(self._host) and (
            host == self._host
            or host.endswith("." + self._host)
            or self._host.endswith("." + host)
        )

    def _landmark(
        self, tag: str, attr: dict[str, str], role: str, page_level: bool, extra: _Extra
    ) -> None:
        labelled = bool(
            attr.get("aria-label", "").strip() or attr.get("aria-labelledby")
        )
        kind: str | None = None
        source = "tag"
        if role in _LANDMARK_ROLES and not (role == "region" and not labelled):
            kind, source = role, "role"
        elif tag == "main":
            kind = "main"
        elif tag == "nav":
            kind = "navigation"
        elif tag == "aside":
            kind = "complementary"
        elif tag == "article":
            kind = "article"
        elif tag == "search":
            kind = "search"
        elif tag == "header" and page_level:
            kind = "banner"
        elif tag == "footer" and page_level:
            kind = "contentinfo"
        elif tag == "section" and labelled:
            kind = "region"
        if kind is None:
            return
        if len(self.landmarks) >= self._cfg.max_landmarks:
            self.truncated.add("landmarks")
            return
        label = squash(attr.get("aria-label", ""))[:200] or None
        landmark = {"kind": kind, "source": source, "labelled": labelled,
                    "label": label, "text_chars": 0}  # fmt: skip
        self.landmarks.append(landmark)
        self._open_landmarks.append(landmark)
        extra.landmark = landmark

    # -- images ----------

    def _image(self, attr: dict[str, str]) -> None:
        if len(self.images) >= self._cfg.max_images:
            self.truncated.add("images")
            return
        alt = attr.get("alt") if "alt" in attr else None
        role = attr.get("role", "").strip().lower()
        record: dict[str, Any] = {
            "src": self._url(attr["src"]) if "src" in attr else None,
            "alt": None if alt is None else squash(alt)[:500],
            "width": _dimension(attr.get("width")),
            "height": _dimension(attr.get("height")),
            "loading": attr.get("loading", "").strip().lower()[:20] or None,
            "decorative": (alt is not None and not alt.strip())
            or role in ("presentation", "none")
            or attr.get("aria-hidden", "").strip().lower() == "true",
            "caption": None,
            "context_before": squash(self._tail)[-self._cfg.context_chars :],
            "context_after": "",
            "in_navigation": self._boiler > 0,
        }
        self.images.append(record)
        if len(self._pending) >= 20:
            old = self._pending.pop(0)
            old["rec"]["context_after"] = squash(old["after"])
        pending = {"rec": record, "after": ""}
        self._pending.append(pending)
        if self._anchor is not None:
            self._anchor["has_image"] = True
            if record["alt"]:
                self._anchor.setdefault("alts", []).append(record["alt"])
        if self._figures:
            self._figures[-1]["images"].append(record)

    # -- anchors ----------

    def _open_anchor(self, attr: dict[str, str], extra: _Extra) -> None:
        self._finish_anchor(self._anchor)  # <a> cannot nest: a new one closes the old
        href = attr["href"].strip()
        if not href or href.startswith("#") or len(href) > self._cfg.max_url_length:
            return
        href = href.translate({9: None, 10: None, 13: None}).replace(" ", "%20")
        url = self._resolve(href)
        if url is None or len(url) > self._cfg.max_url_length:
            return
        rel = tuple(dict.fromkeys(attr.get("rel", "").lower().split()))
        anchor = {"href": url, "rel": rel, "has_image": False,
                  "region": "navigation" if self._boiler > 0 else "content",
                  "internal": self._internal(urlsplit(url).hostname or "")}  # fmt: skip
        self._anchor = anchor
        extra.kind, extra.ref = "anchor", anchor

    def _finish_anchor(self, anchor: dict[str, Any] | None) -> None:
        if anchor is None or anchor is not self._anchor:
            return
        self._anchor = None
        text = squash("".join(anchor.get("parts", [])))
        if not text and anchor.get("alts"):
            text = squash(" ".join(anchor["alts"]))
        text = text[: self._cfg.max_anchor_chars]
        key = (anchor["href"], text, anchor["rel"], anchor["region"])
        if key in self._anchor_keys:
            return
        if len(self.anchors) >= self._cfg.max_anchors:
            self.truncated.add("anchors")
            return
        self._anchor_keys.add(key)
        self.anchors.append(
            {
                "href": anchor["href"],
                "text": text,
                "rel": anchor["rel"],
                "internal": anchor["internal"],
                "region": anchor["region"],
                "has_image": anchor["has_image"],
            }  # fmt: skip
        )

    # -- captions and figures ----------

    def _start_caption(self, extra: _Extra, kind: str, owner: dict[str, Any]) -> None:
        holder: dict[str, Any] = {"owner": owner, "kind": kind}
        self._caption = holder
        extra.kind, extra.ref = kind, holder

    def _finish_caption(self, holder: dict[str, Any] | None) -> None:
        if holder is None or holder is not self._caption:
            return
        self._caption = None
        text = squash("".join(holder.get("parts", [])))[: self._cfg.max_cell_chars * 2]
        holder["owner"]["caption"] = text

    def _finish_figure(self, figure: dict[str, Any] | None) -> None:
        if figure is None or figure not in self._figures:
            return
        self._figures.remove(figure)
        if figure["caption"]:
            for record in figure["images"]:
                record["caption"] = figure["caption"]

    # -- tables ----------

    def _open_table(self, attr: dict[str, str], role: str, extra: _Extra) -> None:
        store = len(self.tables) < self._cfg.max_tables
        if not store:
            self.truncated.add("tables")
        table: dict[str, Any] = {
            "caption": None, "header_cells": None, "rows": [], "row_count": 0,
            "column_count": 0, "has_header_cells": False,
            "presentational": role in ("presentation", "none"),
            "store": store, "row": None, "cell": None,
        }  # fmt: skip
        self._tables.append(table)
        extra.kind, extra.ref = "table", table

    def _start_row(self, table: dict[str, Any]) -> None:
        self._finish_cell(table["cell"])
        self._finish_row(table["row"])
        table["row"] = {"cells": [], "count": 0, "th": []}
        table["row_count"] += 1

    def _start_cell(self, table: dict[str, Any], header: bool) -> None:
        if table["row"] is None:
            self._start_row(table)
        self._finish_cell(table["cell"])
        table["cell"] = {"header": header, "parts": [], "used": 0, "row": table["row"]}

    def _finish_cell(self, cell: dict[str, Any] | None) -> None:
        if cell is None:
            return
        for table in self._tables:
            if table["cell"] is cell:
                table["cell"] = None
                row = cell["row"]
                text = squash("".join(cell["parts"]))[: self._cfg.max_cell_chars]
                row["count"] += 1
                if len(row["cells"]) < self._cfg.max_table_cells:
                    row["cells"].append(text)
                if cell["header"]:
                    table["has_header_cells"] = True
                    if len(row["th"]) < self._cfg.max_table_cells:
                        row["th"].append(text)
                return

    def _finish_row(self, row: dict[str, Any] | None) -> None:
        if row is None:
            return
        for table in self._tables:
            if table["row"] is row:
                table["row"] = None
                table["column_count"] = max(table["column_count"], row["count"])
                if row["th"] and table["header_cells"] is None:
                    table["header_cells"] = row["th"]
                if len(table["rows"]) < self._cfg.max_table_rows:
                    table["rows"].append(tuple(row["cells"]))
                elif "tables" not in self.truncated:
                    self.truncated.add("tables")
                return

    def _finish_table(self, table: dict[str, Any] | None) -> None:
        if table is None or table not in self._tables:
            return
        self._finish_cell(table["cell"])
        self._finish_row(table["row"])
        self._tables.remove(table)
        if table["store"]:
            self.tables.append(
                {
                    "caption": table["caption"],
                    "header_cells": tuple(table["header_cells"] or ()),
                    "rows": tuple(table["rows"]),
                    "row_count": table["row_count"],
                    "column_count": table["column_count"],
                    "has_header_cells": table["has_header_cells"],
                    "presentational": table["presentational"],
                }  # fmt: skip
            )

    # -- lists ----------

    def _open_list(self, tag: str, extra: _Extra) -> None:
        store = len(self.lists) < self._cfg.max_lists
        if not store:
            self.truncated.add("lists")
        block: dict[str, Any] = {
            "kind": tag, "items": [], "item_count": 0, "depth": len(self._lists),
            "in_navigation": self._boiler > 0, "store": store, "item": None,
        }  # fmt: skip
        self._lists.append(block)
        extra.kind, extra.ref = "list", block

    def _start_item(self, block: dict[str, Any], tag: str) -> None:
        if (tag == "dt") != (block["kind"] == "dl"):
            return  # <li> belongs to ul/ol, <dt> to dl; anything else is stray
        self._finish_item(block["item"])
        block["item"] = {"parts": [], "used": 0, "list": block}

    def _finish_item(self, item: dict[str, Any] | None) -> None:
        if item is None:
            return
        block = item["list"]
        if block["item"] is not item:
            return
        block["item"] = None
        block["item_count"] += 1
        if len(block["items"]) < self._cfg.max_list_items:
            block["items"].append(
                squash("".join(item["parts"]))[: self._cfg.max_cell_chars]
            )
        elif "lists" not in self.truncated:
            self.truncated.add("lists")

    def _finish_list(self, block: dict[str, Any] | None) -> None:
        if block is None or block not in self._lists:
            return
        self._finish_item(block["item"])
        self._lists.remove(block)
        if block["store"]:
            self.lists.append(
                {
                    "kind": block["kind"],
                    "items": tuple(block["items"]),
                    "item_count": block["item_count"],
                    "depth": block["depth"],
                    "in_navigation": block["in_navigation"],
                }  # fmt: skip
            )

    # -- media ----------

    def _open_media(self, tag: str, attr: dict[str, str], extra: _Extra) -> None:
        media = {
            "kind": tag,
            "src": self._url(attr["src"]) if "src" in attr else None,
            # Captions only apply to video; for audio the question is not asked.
            "has_captions": False if tag == "video" else None,
        }
        self._media = media
        extra.kind, extra.ref = "media", media

    def _finish_media(self, media: dict[str, Any] | None) -> None:
        if media is None or media is not self._media:
            return
        self._media = None
        self._add_media(media)

    def _add_media(self, media: dict[str, Any]) -> None:
        if len(self.media) >= self._cfg.max_media:
            self.truncated.add("media")
            return
        self.media.append(media)

    def _iframe(self, attr: dict[str, str]) -> None:
        url = self._url(attr.get("src", ""))
        host = (urlsplit(url).hostname or "").lower() if url else ""
        if host in self._cfg.video_embed_hosts:
            self._add_media({"kind": "video_embed", "src": url, "has_captions": None})


def _dimension(value: str | None) -> int | None:
    if value is None:
        return None
    match = _DIMENSION.match(value)
    return int(match.group(1)) if match else None
