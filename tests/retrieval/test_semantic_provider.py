"""The Sentence Transformers provider, tested with injected fake models.

Nothing here downloads a model or needs the optional extra.
"""

import json
from pathlib import Path

import pytest

from geoptimiser.retrieval import (
    DenseIndex,
    EmbedderSettings,
    EmbeddingDescriptor,
    EmbeddingError,
    EmbeddingIncompatible,
    EmbeddingUnavailable,
    HashingEmbedder,
    RetrievalSettings,
    Retriever,
    SentenceTransformerConfig,
    SentenceTransformerEmbedder,
    SettingsError,
    build_embedder,
    build_retriever,
    describe,
    load_settings,
    sbert,
)
from geoptimiser.retrieval.sbert import LoadedModel
from tests.retrieval.conftest import chunks_of

REV = "a" * 40
PINNED_MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"


class FakeModel:
    """Maps known words onto fixed axes, so 'meaning' is whatever the test defines."""

    AXES = {"car": 0, "automobile": 0, "vehicle": 0, "fruit": 1, "apple": 1}

    def __init__(self, dims=3, fail=False, scale=1.0):
        self.dims, self.fail, self.scale = dims, fail, scale
        self.calls: list[dict] = []

    def encode(self, texts, **kwargs):
        self.calls.append({"texts": list(texts), **kwargs})
        if self.fail:
            raise RuntimeError("secret-token-123 inside")
        rows = []
        for text in texts:
            vec = [0.0] * self.dims
            for word in text.lower().split():
                if word in self.AXES:
                    vec[self.AXES[word]] += self.scale
            if kwargs.get("normalize_embeddings") and any(vec):
                norm = sum(x * x for x in vec) ** 0.5
                vec = [x / norm for x in vec]
            rows.append(vec)
        return rows


def make_loader(model=None, revision=REV, dims=3, counter=None):
    model = model or FakeModel(dims)

    def loader(config):
        if counter is not None:
            counter.append(config)
        return LoadedModel(
            model=model,
            revision=revision,
            dimensions=dims,
            max_seq_length=256,
            libraries={"sentence-transformers": "9.9"},
        )

    return loader


def embedder(**kw):
    config = kw.pop("config", None)
    return SentenceTransformerEmbedder(config, loader=make_loader(**kw))


# --- configuration -------------------------------------------------------------------


def test_default_config_is_minilm_with_normalisation():
    c = SentenceTransformerConfig()
    assert c.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert (c.device, c.batch_size, c.normalize, c.local_files_only) == (
        "cpu",
        32,
        True,
        False,
    )
    assert c.revision == PINNED_MODEL_REVISION and c.max_seq_length is None


@pytest.mark.parametrize(
    "bad",
    [
        {"batch_size": 0},
        {"batch_size": 10_000},
        {"model_id": " "},
        {"max_seq_length": 2},
    ],
)
def test_invalid_config_is_rejected(bad):
    with pytest.raises(ValueError):
        SentenceTransformerConfig(**bad)


def test_shipped_settings_file_selects_the_real_model():
    settings = load_settings(Path("configs/retrieval.json"))
    assert settings.embedder.kind == "sentence-transformers"
    assert settings.embedder.sentence_transformers.model_id.endswith("all-MiniLM-L6-v2")
    assert settings.embedder.sentence_transformers.revision == PINNED_MODEL_REVISION


def test_settings_errors_name_the_file(tmp_path):
    bad = tmp_path / "s.json"
    bad.write_text('{"embedder": {"kind": "nope"}}')
    with pytest.raises(SettingsError, match="s.json"):
        load_settings(bad)
    bad.write_text("{")
    with pytest.raises(SettingsError, match="invalid JSON"):
        load_settings(bad)
    with pytest.raises(SettingsError, match="cannot read"):
        load_settings(tmp_path / "missing.json")


# --- descriptor, dimensions, normalisation --------------------------------------------


def test_descriptor_records_model_revision_dimension_and_normalisation():
    e = embedder(config=SentenceTransformerConfig(normalize=True))
    d = e.descriptor
    assert isinstance(d, EmbeddingDescriptor)
    assert d.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert d.revision == REV and d.dimensions == 3 and e.dimensions == 3
    assert d.normalized is True and d.similarity == "cosine" and d.semantic is True
    assert d.max_seq_length == 256 and d.libraries == {"sentence-transformers": "9.9"}
    assert REV in e.version and "normalize=True" in e.version
    assert describe(e) == d


def test_normalisation_setting_reaches_the_model_and_changes_the_version():
    model = FakeModel()
    on = SentenceTransformerEmbedder(
        SentenceTransformerConfig(normalize=True), loader=make_loader(model)
    )
    off = SentenceTransformerEmbedder(
        SentenceTransformerConfig(normalize=False), loader=make_loader(model)
    )
    (vec_on,) = on.embed(["car car"])
    (vec_off,) = off.embed(["car car"])
    assert vec_on == pytest.approx([1.0, 0.0, 0.0])
    assert vec_off == pytest.approx([2.0, 0.0, 0.0])
    assert model.calls[0]["normalize_embeddings"] is True
    assert model.calls[1]["normalize_embeddings"] is False
    assert on.version != off.version
    assert on.descriptor.compatibility_key() != off.descriptor.compatibility_key()


def test_embed_batches_and_never_shows_a_progress_bar():
    model = FakeModel()
    e = SentenceTransformerEmbedder(
        SentenceTransformerConfig(batch_size=7), loader=make_loader(model)
    )
    e.embed(["car", "fruit"])
    assert model.calls[0]["batch_size"] == 7
    assert model.calls[0]["show_progress_bar"] is False
    assert model.calls[0]["texts"] == ["car", "fruit"]


def test_model_is_loaded_once_across_documents_and_queries():
    loads: list = []
    e = embedder(counter=loads)
    chunks = chunks_of({"d1": "car park", "d2": "apple fruit"})
    index = DenseIndex(chunks, e)
    for query in ("vehicle", "fruit", "car"):
        index.search(query, 2)
    _ = e.descriptor, e.dimensions, e.version
    assert len(loads) == 1


def test_loading_is_lazy():
    loads: list = []
    embedder(counter=loads)
    assert loads == []


# --- empty input, bad input, failures -------------------------------------------------


def test_empty_input_returns_nothing_without_loading():
    loads: list = []
    e = embedder(counter=loads)
    assert e.embed([]) == [] and loads == []


@pytest.mark.parametrize("bad", ["a bare string", [1, 2], ["ok", None]])
def test_non_string_input_is_rejected(bad):
    with pytest.raises(EmbeddingError, match="strings"):
        embedder().embed(bad)


def test_blank_strings_are_embedded_not_dropped():
    out = embedder().embed(["", "  ", "car"])
    assert len(out) == 3 and out[0] == [0.0, 0.0, 0.0]


def test_encoding_failure_is_contained_and_leaks_nothing():
    e = SentenceTransformerEmbedder(loader=make_loader(FakeModel(fail=True)))
    with pytest.raises(EmbeddingError) as err:
        e.embed(["car"])
    assert "secret-token" not in str(err.value) and "RuntimeError" in str(err.value)


def test_wrong_width_output_is_rejected():
    e = SentenceTransformerEmbedder(loader=make_loader(FakeModel(dims=5), dims=3))
    with pytest.raises(EmbeddingError, match="unexpected shape"):
        e.embed(["car"])


def test_loader_failure_is_unavailable_and_leaks_nothing():
    def boom(config):
        raise OSError("/home/secret/path")

    e = SentenceTransformerEmbedder(loader=boom)
    for call in (lambda: e.embed(["x"]), lambda: e.dimensions, lambda: e.descriptor):
        with pytest.raises(EmbeddingUnavailable) as err:
            call()
        assert "secret" not in str(err.value) and "OSError" in str(err.value)


def test_missing_extra_gives_an_install_hint(monkeypatch):
    real_import = sbert.importlib.import_module

    def fake_import(name, *a, **k):
        if name in {"sentence_transformers", "huggingface_hub"}:
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(sbert.importlib, "import_module", fake_import)
    with pytest.raises(EmbeddingUnavailable, match=r"geoptimiser\[semantic\]"):
        sbert.default_loader(SentenceTransformerConfig())


def test_unreachable_hub_is_unavailable_not_a_crash(monkeypatch):
    class Hub:
        @staticmethod
        def snapshot_download(**kwargs):
            raise ConnectionError("offline")

    class ST:
        SentenceTransformer = object

    mods = {"sentence_transformers": ST, "huggingface_hub": Hub}
    monkeypatch.setattr(sbert.importlib, "import_module", lambda n, *a, **k: mods[n])
    with pytest.raises(EmbeddingUnavailable, match="ConnectionError"):
        sbert.default_loader(SentenceTransformerConfig())


def test_default_loader_uses_only_safetensors_and_pins_the_snapshot(
    tmp_path, monkeypatch
):
    snapshot = tmp_path / "models--x--y" / "snapshots" / REV
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(b"safe-weights")
    (snapshot / "pytorch_model.bin").write_bytes(b"pickle-weights")
    captured = {"download": None, "model": None}

    class Hub:
        @staticmethod
        def snapshot_download(**kwargs):
            captured["download"] = kwargs
            return str(snapshot)

    class Model:
        max_seq_length = 128

        @staticmethod
        def get_sentence_embedding_dimension():
            return 384

    class ST:
        @staticmethod
        def SentenceTransformer(location, **kwargs):
            captured["model"] = {"location": location, **kwargs}
            return Model()

    modules = {"sentence_transformers": ST, "huggingface_hub": Hub}
    monkeypatch.setattr(
        sbert.importlib, "import_module", lambda name, *a, **k: modules[name]
    )

    loaded = sbert.default_loader(SentenceTransformerConfig(revision=REV))

    assert loaded.revision == REV
    assert "*.bin" in captured["download"]["ignore_patterns"]
    assert "*.pt" in captured["download"]["ignore_patterns"]
    assert captured["download"]["revision"] == REV
    assert captured["model"]["trust_remote_code"] is False
    assert captured["model"]["model_kwargs"] == {"use_safetensors": True}


def test_default_loader_refuses_a_snapshot_without_safetensors(tmp_path, monkeypatch):
    snapshot = tmp_path / "models--x--y" / "snapshots" / REV
    snapshot.mkdir(parents=True)
    (snapshot / "pytorch_model.bin").write_bytes(b"pickle-weights")

    class Hub:
        @staticmethod
        def snapshot_download(**kwargs):
            return str(snapshot)

    class ST:
        SentenceTransformer = object

    modules = {"sentence_transformers": ST, "huggingface_hub": Hub}
    monkeypatch.setattr(
        sbert.importlib, "import_module", lambda name, *a, **k: modules[name]
    )

    with pytest.raises(EmbeddingUnavailable, match="no .safetensors weights"):
        sbert.default_loader(SentenceTransformerConfig(revision=REV))


def test_revision_from_snapshot(tmp_path):
    snap = tmp_path / "models--x--y" / "snapshots" / REV
    assert sbert.revision_from_snapshot(snap, None) == REV
    assert sbert.revision_from_snapshot(snap, REV) == REV
    assert sbert.revision_from_snapshot(snap, "main") == REV  # branch names resolve
    with pytest.raises(EmbeddingError, match="pinned revision"):
        sbert.revision_from_snapshot(snap, "b" * 40)
    with pytest.raises(EmbeddingError, match="cannot determine"):
        sbert.revision_from_snapshot(tmp_path / "model", None)


def test_local_directory_revision_tracks_content(tmp_path):
    (tmp_path / "w.bin").write_bytes(b"one")
    first = sbert.local_directory_revision(tmp_path)
    assert first.startswith("local:") and first == sbert.local_directory_revision(
        tmp_path
    )
    (tmp_path / "w.bin").write_bytes(b"two")
    assert sbert.local_directory_revision(tmp_path) != first


# --- index compatibility ---------------------------------------------------------------


def corpus():
    return chunks_of({"d1": "the car", "d2": "an apple", "d3": "other words"})


def test_index_ranks_by_the_models_notion_of_similarity():
    index = DenseIndex(corpus(), embedder())
    hits = index.search("vehicle", 3)  # shares no word with "the car"
    ids = {c.chunk_id: c.text for c in corpus()}
    assert [ids[h.chunk_id] for h in hits] == ["the car"]
    assert index.descriptor.revision == REV


def test_index_rejects_a_model_swapped_after_build():
    first = embedder(revision="a" * 40)
    index = DenseIndex(corpus(), first)
    index.provider = embedder(revision="b" * 40)  # different revision, same shape
    with pytest.raises(EmbeddingIncompatible, match="changed since"):
        index.search("car", 2)


def test_index_rejects_a_dimension_change():
    index = DenseIndex(corpus(), embedder(dims=3))
    index.provider = embedder(dims=4)
    with pytest.raises(EmbeddingIncompatible):
        index.search("car", 2)


def test_index_rejects_a_query_vector_of_the_wrong_size():
    class Drifting(HashingEmbedder):
        broken = False

        def embed(self, texts):
            vectors = super().embed(texts)
            return [v[:-1] for v in vectors] if self.broken else vectors

    provider = Drifting(16)
    index = DenseIndex(corpus(), provider)
    provider.broken = True
    with pytest.raises(EmbeddingIncompatible, match="dimensions"):
        index.search("car", 2)


def test_saved_index_loads_only_for_the_same_model_and_corpus(tmp_path):
    chunks = corpus()
    path = tmp_path / "dense.json"
    DenseIndex(chunks, embedder()).save(path)
    again = DenseIndex.load(path, chunks, embedder())
    assert again.search("vehicle", 1) == DenseIndex(chunks, embedder()).search(
        "vehicle", 1
    )
    with pytest.raises(EmbeddingIncompatible):
        DenseIndex.load(path, chunks, embedder(revision="c" * 40))
    with pytest.raises(EmbeddingIncompatible):
        DenseIndex.load(path, chunks, HashingEmbedder(3 * 8))
    with pytest.raises(EmbeddingError, match="different chunk set"):
        DenseIndex.load(path, chunks[:2], embedder())
    with pytest.raises(FileExistsError):
        DenseIndex(chunks, embedder()).save(path)


def test_corrupt_or_foreign_index_files_are_rejected(tmp_path):
    chunks = corpus()
    path = tmp_path / "dense.json"
    path.write_text("{")
    with pytest.raises(EmbeddingError, match="unreadable"):
        DenseIndex.load(path, chunks, embedder())
    DenseIndex(chunks, embedder()).save(tmp_path / "ok.json")
    data = json.loads((tmp_path / "ok.json").read_text())
    data["schema_version"] = 99
    path.write_text(json.dumps(data))
    with pytest.raises(EmbeddingError, match="schema version"):
        DenseIndex.load(path, chunks, embedder())


def test_fingerprint_changes_with_model_revision():
    a = DenseIndex(corpus(), embedder(revision="a" * 40)).fingerprint
    b = DenseIndex(corpus(), embedder(revision="b" * 40)).fingerprint
    assert a != b


# --- no silent fallback ------------------------------------------------------------------


def test_hashing_embedder_is_refused_unless_explicitly_allowed():
    settings = EmbedderSettings(kind="hashing-test")
    with pytest.raises(EmbeddingUnavailable, match="not semantic"):
        build_embedder(settings)
    assert isinstance(
        build_embedder(settings, allow_test_embedder=True), HashingEmbedder
    )


def test_unavailable_model_fails_retriever_construction_without_fallback():
    def unavailable(config):
        raise EmbeddingUnavailable("no weights")

    with pytest.raises(EmbeddingUnavailable):
        build_retriever(corpus(), RetrievalSettings(), loader=unavailable)


def test_configured_path_uses_the_semantic_provider_for_dense_and_hybrid():
    retriever = build_retriever(corpus(), RetrievalSettings(), loader=make_loader())
    assert isinstance(retriever.embedder, SentenceTransformerEmbedder)
    assert retriever.embedder.semantic
    assert {"dense", "hybrid"} <= set(retriever.available_modes())
    texts = {c.chunk_id: c.text for c in corpus()}
    for mode in ("dense", "hybrid"):
        top = retriever.retrieve("vehicle", mode, 1).hits[0]
        assert texts[top.chunk_id] == "the car"
    # lexical alone cannot do this: "vehicle" appears in no chunk
    assert retriever.retrieve("vehicle", "lexical").hits == ()


def test_require_semantic_rejects_the_test_embedder_and_missing_embedder():
    with pytest.raises(ValueError, match="non-semantic"):
        Retriever(corpus(), embedder=HashingEmbedder(), require_semantic=True)
    with pytest.raises(ValueError, match="missing"):
        Retriever(corpus(), require_semantic=True)
    Retriever(corpus(), embedder=embedder(), require_semantic=True)


def test_test_path_still_allows_the_hashing_embedder():
    r = build_retriever(
        corpus(),
        RetrievalSettings(embedder=EmbedderSettings(kind="hashing-test")),
        allow_test_embedder=True,
    )
    assert r.embedder is not None and not r.embedder.semantic


def test_importing_the_package_does_not_import_the_heavy_stack():
    import subprocess
    import sys

    code = (
        "import sys, geoptimiser.retrieval; "
        "sys.exit(any(m in sys.modules for m in ('sentence_transformers', 'torch')))"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
