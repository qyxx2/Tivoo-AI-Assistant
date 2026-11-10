from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "services"))

KWS_DIR = "kws/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
STT_DIR = "stt/sherpa-onnx-paraformer-zh-small-2024-03-09"
TTS_DIR = "tts/matcha-icefall-zh-baker"

CHECKSUMMED_FILES = (
    f"{KWS_DIR}/encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    f"{KWS_DIR}/decoder-epoch-13-avg-2-chunk-16-left-64.onnx",
    f"{KWS_DIR}/joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    f"{KWS_DIR}/tokens.txt",
    f"{KWS_DIR}/en.phone",
    f"{STT_DIR}/model.int8.onnx",
    f"{STT_DIR}/tokens.txt",
    f"{TTS_DIR}/model-steps-3.onnx",
    f"{TTS_DIR}/tokens.txt",
    f"{TTS_DIR}/lexicon.txt",
    f"{TTS_DIR}/phone.fst",
    f"{TTS_DIR}/date.fst",
    f"{TTS_DIR}/number.fst",
    "tts/vocos-22khz-univ.onnx",
)


@pytest.fixture
def valid_model_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    models_dir = tmp_path / "models"
    manifest_lines = []
    for index, relative_path in enumerate(CHECKSUMMED_FILES):
        path = models_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = f"test model asset {index}: {relative_path}".encode()
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        manifest_lines.append(f"{digest}  {relative_path}")

    keywords = models_dir / KWS_DIR / "keywords.txt"
    keywords.parent.mkdir(parents=True, exist_ok=True)
    keywords.write_text("test keyword @test_keyword\n", encoding="utf-8")

    manifest = tmp_path / "MODEL_SHA256SUMS"
    manifest.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    monkeypatch.setattr("sherpa_wyoming.model_utils.DEFAULT_MANIFEST_PATH", manifest)
    return models_dir
