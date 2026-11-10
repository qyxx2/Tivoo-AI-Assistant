from __future__ import annotations

from pathlib import Path

import pytest
from sherpa_wyoming import models
from sherpa_wyoming.config import load_config
from sherpa_wyoming.model_utils import (
    ModelAssetError,
    get_model_paths,
    verify_model_files,
)


def test_model_paths_use_separate_fixed_model_directories(tmp_path: Path) -> None:
    paths = get_model_paths(tmp_path)

    assert (
        paths.kws_dir == tmp_path / "kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
    )
    assert paths.stt_model.name == "model.int8.onnx"
    assert paths.tts_vocoder == tmp_path / "tts/vocos-22khz-univ.onnx"
    assert paths.tts_model.name == "model-steps-3.onnx"


def test_verify_model_files_checks_every_required_hash(
    valid_model_assets: Path,
) -> None:
    verified = verify_model_files(valid_model_assets)

    assert len(verified) == 14
    assert all(path.is_file() for path in verified.values())


def test_verify_model_files_rejects_missing_asset(
    valid_model_assets: Path,
) -> None:
    paths = get_model_paths(valid_model_assets)
    paths.stt_tokens.unlink()

    with pytest.raises(ModelAssetError, match="tokens.txt"):
        verify_model_files(valid_model_assets)


def test_verify_model_files_rejects_hash_mismatch(
    valid_model_assets: Path,
) -> None:
    paths = get_model_paths(valid_model_assets)
    paths.tts_model.write_bytes(b"corrupted model")

    with pytest.raises(ModelAssetError, match="SHA-256 mismatch"):
        verify_model_files(valid_model_assets)


def test_verify_model_files_rejects_manifest_without_kws_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "MODEL_SHA256SUMS"
    manifest.write_text("", encoding="utf-8")
    monkeypatch.setattr("sherpa_wyoming.model_utils.DEFAULT_MANIFEST_PATH", manifest)

    with pytest.raises(ModelAssetError, match="missing SHA-256 entry"):
        verify_model_files(tmp_path)


def test_verify_model_files_rejects_malformed_manifest(
    valid_model_assets: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = valid_model_assets.parent / "bad-SHA256SUMS"
    manifest.write_text("not-a-checksum  kws/model.onnx\n", encoding="utf-8")
    monkeypatch.setattr("sherpa_wyoming.model_utils.DEFAULT_MANIFEST_PATH", manifest)

    with pytest.raises(ModelAssetError, match="invalid checksum manifest"):
        verify_model_files(valid_model_assets)


def test_load_models_constructs_each_model_once(
    valid_model_assets: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: dict[str, object] = {
        "kws": object(),
        "stt": object(),
        "tts": object(),
    }
    calls: list[str] = []
    monkeypatch.setattr(
        models,
        "_load_keyword_spotter",
        lambda config, paths: calls.append("kws") or created["kws"],
    )
    monkeypatch.setattr(
        models,
        "_load_stt_recognizer",
        lambda config, paths: calls.append("stt") or created["stt"],
    )
    monkeypatch.setattr(
        models,
        "_load_tts_engine",
        lambda config, paths: calls.append("tts") or created["tts"],
    )
    config = load_config(
        {"WAKE_WORD_PHRASE": "Hi Tivoo", "MODELS_DIR": str(valid_model_assets)}
    )

    bundle = models.load_models(config)

    assert isinstance(bundle, models.ModelBundle)
    assert bundle.keyword_spotter is created["kws"]
    assert bundle.stt_recognizer is created["stt"]
    assert bundle.tts_engine is created["tts"]
    assert calls == ["kws", "stt", "tts"]


@pytest.mark.parametrize("failed_model", ["kws", "stt", "tts"])
def test_load_models_never_returns_partial_bundle_on_model_error(
    valid_model_assets: Path,
    monkeypatch: pytest.MonkeyPatch,
    failed_model: str,
) -> None:
    def factory(name: str):
        def build(config, paths):
            if name == failed_model:
                raise RuntimeError("simulated loader failure")
            return object()

        return build

    monkeypatch.setattr(models, "_load_keyword_spotter", factory("kws"))
    monkeypatch.setattr(models, "_load_stt_recognizer", factory("stt"))
    monkeypatch.setattr(models, "_load_tts_engine", factory("tts"))
    config = load_config(
        {"WAKE_WORD_PHRASE": "Hi Tivoo", "MODELS_DIR": str(valid_model_assets)}
    )

    with pytest.raises(models.ModelLoadError, match=failed_model.upper()):
        models.load_models(config)


def test_load_models_passes_cpu_provider_and_contract_arguments(
    valid_model_assets: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, dict] = {}

    class FakeKeywordSpotter:
        def __init__(self, **kwargs):
            captured["kws"] = kwargs

    class FakeOfflineRecognizer:
        @classmethod
        def from_paraformer(cls, **kwargs):
            captured["stt"] = kwargs
            return object()

    class FakeMatchaConfig:
        def __init__(self, **kwargs):
            captured["matcha"] = kwargs

    class FakeTtsModelConfig:
        def __init__(self, **kwargs):
            captured["tts_model"] = kwargs

    class FakeTtsConfig:
        def __init__(self, **kwargs):
            captured["tts"] = kwargs

        def validate(self):
            return True

    class FakeOfflineTts:
        def __init__(self, config):
            captured["tts_instance"] = {"config": config}

    monkeypatch.setattr(models.sherpa_onnx, "KeywordSpotter", FakeKeywordSpotter)
    monkeypatch.setattr(models.sherpa_onnx, "OfflineRecognizer", FakeOfflineRecognizer)
    monkeypatch.setattr(
        models.sherpa_onnx, "OfflineTtsMatchaModelConfig", FakeMatchaConfig
    )
    monkeypatch.setattr(models.sherpa_onnx, "OfflineTtsModelConfig", FakeTtsModelConfig)
    monkeypatch.setattr(models.sherpa_onnx, "OfflineTtsConfig", FakeTtsConfig)
    monkeypatch.setattr(models.sherpa_onnx, "OfflineTts", FakeOfflineTts)
    config = load_config(
        {"WAKE_WORD_PHRASE": "Hi Tivoo", "MODELS_DIR": str(valid_model_assets)}
    )

    models._load_keyword_spotter(config, get_model_paths(valid_model_assets))
    models._load_stt_recognizer(config, get_model_paths(valid_model_assets))
    models._load_tts_engine(config, get_model_paths(valid_model_assets))

    assert captured["kws"]["provider"] == "cpu"
    assert captured["kws"]["num_threads"] == 1
    assert captured["kws"]["keywords_score"] == 1.0
    assert captured["kws"]["keywords_threshold"] == 0.25
    assert captured["stt"]["provider"] == "cpu"
    assert captured["stt"]["num_threads"] == 2
    assert captured["stt"]["decoding_method"] == "greedy_search"
    assert captured["matcha"]["vocoder"].endswith("vocos-22khz-univ.onnx")
    assert captured["tts"]["rule_fsts"].endswith(
        "phone.fst,"
        + str(get_model_paths(valid_model_assets).tts_date_fst)
        + ","
        + str(get_model_paths(valid_model_assets).tts_number_fst)
    )
    assert captured["tts"]["max_num_sentences"] == 1
