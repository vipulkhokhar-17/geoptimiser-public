"""Extraction limits. Operational limits live here, not in the shared schemas."""

from pydantic import BaseModel, ConfigDict, Field

EXTRACTION_VERSION = "html-extractor:3"
# Highest PageDocument detail level this extractor produces (see schemas).
DETAIL_LEVEL = 2


class ExtractionConfig(BaseModel):
    """Bounds for extracting one page. Every limit is finite and positive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_input_bytes: int = Field(default=2_000_000, ge=1)
    max_text_chars: int = Field(default=200_000, ge=1)
    max_headings: int = Field(default=500, ge=1)
    max_heading_chars: int = Field(default=500, ge=1)
    max_links: int = Field(default=2_000, ge=1)
    max_url_length: int = Field(default=2_048, ge=16)
    max_json_ld_blocks: int = Field(default=50, ge=1)
    max_json_ld_bytes: int = Field(default=262_144, ge=1)
    max_types: int = Field(default=100, ge=1)
    max_nesting_depth: int = Field(default=256, ge=1)
    max_seconds: float = Field(default=10.0, gt=0)
    # Above this share of U+FFFD in the decoded text, decoding is declared failed.
    max_replacement_ratio: float = Field(default=0.1, gt=0, le=1)
    # Rich extraction (images, anchors, landmarks, tables, lists, media).
    max_images: int = Field(default=500, ge=1)
    max_anchors: int = Field(default=2_000, ge=1)
    max_landmarks: int = Field(default=100, ge=1)
    max_tables: int = Field(default=50, ge=1)
    max_table_rows: int = Field(default=25, ge=1)
    max_table_cells: int = Field(default=20, ge=1)
    max_lists: int = Field(default=100, ge=1)
    max_list_items: int = Field(default=50, ge=1)
    max_media: int = Field(default=50, ge=1)
    max_cell_chars: int = Field(default=120, ge=1)
    max_anchor_chars: int = Field(default=300, ge=1)
    context_chars: int = Field(default=120, ge=1)
    max_attr_chars: int = Field(default=500, ge=1)
    # iframe hosts treated as embedded video players (configuration, not a registry).
    video_embed_hosts: tuple[str, ...] = (
        "youtube.com",
        "www.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "player.vimeo.com",
    )
