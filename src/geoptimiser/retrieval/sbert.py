"""Local Sentence Transformers embeddings (Stage 08 extension, ADR-0022).

The heavy model stack is an optional extra (``pip install 'geoptimiser[semantic]'``)
and is imported only when a model is first needed. Inference runs locally; the model
is loaded once per provider and documents are encoded in batches. Pin ``revision``
to make downloads reproducible.

Hub snapshots exclude pickle-oriented weight formats. Before loading, the provider
requires at least one Safetensors weight file and explicitly requests Safetensors from
Transformers. Remote model code is never trusted.

This provider never falls back to another embedder: when the extra or the weights are
missing it raises ``EmbeddingUnavailable``.
"""

import hashlib
import importlib
import importlib.metadata
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from geoptimiser.retrieval.dense import (
    EmbeddingDescriptor,
    EmbeddingError,
    EmbeddingUnavailable,
)
from geoptimiser.schemas import NonBlankStr, SchemaModel

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Hugging Face commit for the default model. Keep configs/retrieval.json in sync.
DEFAULT_MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
INSTALL_HINT = "install the optional extra with: pip install 'geoptimiser[semantic]'"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_IGNORED_WEIGHT_FORMATS = [
    "onnx/*",
    "openvino/*",
    "*.bin",
    "*.pt",
    "*.pth",
    "*.pkl",
    "*.pickle",
    "*.h5",
    "*.msgpack",
    "*.ot",
    "*.ckpt",
]


class SentenceTransformerConfig(SchemaModel):
    model_id: NonBlankStr = DEFAULT_MODEL  # a Hub id or a local model directory
    revision: NonBlankStr | None = DEFAULT_MODEL_REVISION
    device: NonBlankStr = "cpu"
    batch_size: int = Field(default=32, ge=1, le=512)
    normalize: bool = True  # ask the model for unit-length vectors
    max_seq_length: int | None = Field(default=None, ge=8, le=8192)
    local_files_only: bool = False  # never touch the network (use the cache)


@dataclass(frozen=True)
class LoadedModel:
    """What a loader returns: a model with ``encode`` plus its identity."""

    model: Any
    revision: str
    dimensions: int
    max_seq_length: int | None
    libraries: dict[str, str]


Loader = Callable[[SentenceTransformerConfig], LoadedModel]


def revision_from_snapshot(snapshot: Path, requested: str | None) -> str:
    """The commit hash of a Hub snapshot directory (``.../snapshots/<hash>``).

    Raises ``EmbeddingError`` when a pinned 40-character commit was requested and a
    different one was resolved.
    """
    commit = snapshot.name if snapshot.parent.name == "snapshots" else None
    if commit is None:
        raise EmbeddingError("cannot determine the model revision from the cache path")
    if requested and _COMMIT.match(requested) and commit != requested:
        raise EmbeddingError(
            f"pinned revision {requested[:12]} but resolved {commit[:12]}"
        )
    return commit


def local_directory_revision(directory: Path) -> str:
    """``local:<sha256>`` over the file names and bytes of a local model directory."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(directory)).encode())
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return "local:" + digest.hexdigest()


def _require_safetensors(directory: Path) -> None:
    """Refuse snapshots that would require pickle-based PyTorch weight files."""
    if not any(path.is_file() for path in directory.rglob("*.safetensors")):
        raise EmbeddingUnavailable(
            "the model directory contains no .safetensors weights; "
            "refusing to load pickle-based model weights"
        )


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def default_loader(config: SentenceTransformerConfig) -> LoadedModel:
    """Load a real Sentence Transformers model (requires the ``semantic`` extra)."""
    try:
        st = importlib.import_module("sentence_transformers")
        hub = importlib.import_module("huggingface_hub")
    except ImportError as exc:
        raise EmbeddingUnavailable(
            f"sentence-transformers is not installed; {INSTALL_HINT}"
        ) from exc
    try:
        directory = Path(config.model_id)
        if directory.is_dir():
            location = str(directory)
            revision = local_directory_revision(directory)
            _require_safetensors(directory)
        else:
            snapshot = Path(
                hub.snapshot_download(
                    repo_id=config.model_id,
                    revision=config.revision,
                    local_files_only=config.local_files_only,
                    ignore_patterns=_IGNORED_WEIGHT_FORMATS,
                )
            )
            location, revision = (
                str(snapshot),
                revision_from_snapshot(snapshot, config.revision),
            )
            _require_safetensors(snapshot)
        model = st.SentenceTransformer(
            location,
            device=config.device,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        if config.max_seq_length is not None:
            model.max_seq_length = config.max_seq_length
        dims_of = (
            getattr(model, "get_embedding_dimension", None)
            or model.get_sentence_embedding_dimension
        )
        dimensions = int(dims_of())
    except EmbeddingError:
        raise
    except Exception as exc:  # network, missing weights, corrupt cache ...
        raise EmbeddingUnavailable(
            f"could not load {config.model_id!r} ({type(exc).__name__}); check network "
            "access to the Hugging Face Hub, or download the model first and set "
            "local_files_only"
        ) from exc
    libraries = {
        name: v
        for name in ("sentence-transformers", "torch", "transformers")
        if (v := _version(name))
    }
    return LoadedModel(
        model=model,
        revision=revision,
        dimensions=dimensions,
        max_seq_length=getattr(model, "max_seq_length", None),
        libraries=libraries,
    )


class SentenceTransformerEmbedder:
    """An ``EmbeddingProvider`` backed by a local Sentence Transformers model."""

    name = "sentence-transformers"
    semantic = True

    def __init__(
        self,
        config: SentenceTransformerConfig | None = None,
        *,
        loader: Loader = default_loader,
    ) -> None:
        self.config = config or SentenceTransformerConfig()
        self._loader = loader
        self._loaded: LoadedModel | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> LoadedModel:
        """Load the model on first use, exactly once."""
        with self._lock:
            if self._loaded is None:
                try:
                    self._loaded = self._loader(self.config)
                except EmbeddingError:
                    raise
                except Exception as exc:
                    raise EmbeddingUnavailable(
                        f"loading {self.config.model_id!r} failed "
                        f"({type(exc).__name__})"
                    ) from exc
            return self._loaded

    @property
    def dimensions(self) -> int:
        return self._ensure().dimensions

    @property
    def version(self) -> str:
        loaded = self._ensure()
        return (
            f"{loaded.revision}|normalize={self.config.normalize}"
            f"|max_seq_length={loaded.max_seq_length}"
        )

    @property
    def descriptor(self) -> EmbeddingDescriptor:
        loaded = self._ensure()
        return EmbeddingDescriptor(
            name=self.name,
            version=self.version,
            dimensions=loaded.dimensions,
            semantic=True,
            model_id=self.config.model_id,
            revision=loaded.revision,
            normalized=self.config.normalize,
            max_seq_length=loaded.max_seq_length,
            libraries=loaded.libraries,
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Encode ``texts`` in batches; an empty input gives an empty result."""
        if isinstance(texts, str) or any(not isinstance(t, str) for t in texts):
            raise EmbeddingError("embed() takes a sequence of strings")
        if not texts:
            return []
        loaded = self._ensure()
        try:
            vectors = loaded.model.encode(
                list(texts),
                batch_size=self.config.batch_size,
                normalize_embeddings=self.config.normalize,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            rows = [[float(x) for x in row] for row in vectors]
        except Exception as exc:
            raise EmbeddingError(
                f"{self.config.model_id} encoding failed ({type(exc).__name__})"
            ) from exc
        if len(rows) != len(texts) or any(len(r) != loaded.dimensions for r in rows):
            raise EmbeddingError(
                f"{self.config.model_id} returned vectors of an unexpected shape"
            )
        return rows
