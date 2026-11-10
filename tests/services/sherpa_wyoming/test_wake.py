from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sherpa_wyoming import model_utils
from sherpa_wyoming.config import load_config
from sherpa_wyoming.providers.wake import WAKE_WORD_ID, WakeWordProvider
from wyoming.audio import AudioChunk, AudioStart
from wyoming.error import Error
from wyoming.wake import Detect, Detection, NotDetected


class FakeStream:
    def __init__(self) -> None:
        self.accepted: list[tuple[int, np.ndarray]] = []
        self.ready = False

    def accept_waveform(self, rate: int, samples: np.ndarray) -> None:
        self.accepted.append((rate, samples.copy()))
        self.ready = True


class FakeKeywordSpotter:
    def __init__(self, results: list[str] | None = None, fail: bool = False) -> None:
        self.results = list(results or [])
        self.fail = fail
        self.streams: list[FakeStream] = []
        self.decode_count = 0

    def create_stream(self) -> FakeStream:
        stream = FakeStream()
        self.streams.append(stream)
        return stream

    def is_ready(self, stream: FakeStream) -> bool:
        return stream.ready

    def decode_stream(self, stream: FakeStream) -> None:
        if self.fail:
            raise RuntimeError("simulated KWS failure")
        stream.ready = False
        self.decode_count += 1

    def get_result(self, stream: FakeStream) -> str:
        if self.fail:
            raise RuntimeError("simulated KWS result failure")
        return self.results.pop(0) if self.results else ""


@pytest.fixture
def service_config(tmp_path: Path):
    return load_config({"WAKE_WORD_PHRASE": "你好 Tivoo", "MODELS_DIR": str(tmp_path)})


def _provider(config, spotter: FakeKeywordSpotter) -> WakeWordProvider:
    return WakeWordProvider(config, spotter)


def _start(session) -> None:
    assert session.handle_event(Detect(names=[WAKE_WORD_ID])) is None
    assert session.handle_event(AudioStart(rate=16_000, width=2, channels=1)) is None


def _chunk(samples: list[int], timestamp: int) -> AudioChunk:
    return AudioChunk(
        rate=16_000,
        width=2,
        channels=1,
        audio=np.asarray(samples, dtype="<i2").tobytes(),
        timestamp=timestamp,
    )


@pytest.mark.parametrize("names", [[WAKE_WORD_ID], None, []])
def test_detect_accepts_the_configured_or_only_default_model(
    service_config, names
) -> None:
    spotter = FakeKeywordSpotter()
    session = _provider(service_config, spotter).create_session()

    assert session.handle_event(Detect(names=names)) is None
    assert len(spotter.streams) == 1
    assert session.stream is spotter.streams[0]


@pytest.mark.parametrize("names", [["not-tivoo"], [WAKE_WORD_ID, "not-tivoo"]])
def test_detect_rejects_any_unadvertised_model_id(service_config, names) -> None:
    spotter = FakeKeywordSpotter()
    session = _provider(service_config, spotter).create_session()

    response = session.handle_event(Detect(names=names))

    assert isinstance(response, Error)
    assert response.code == "unsupported_model"
    assert spotter.streams == []
    assert session.on_eof() is None


def test_audio_start_requires_16khz_s16le_mono(service_config) -> None:
    spotter = FakeKeywordSpotter()
    session = _provider(service_config, spotter).create_session()
    assert session.handle_event(Detect(names=[WAKE_WORD_ID])) is None

    response = session.handle_event(AudioStart(rate=48_000, width=2, channels=2))

    assert isinstance(response, Error)
    assert response.code == "audio_format"
    assert session.stream is None
    assert session.on_eof() is None


def test_chunks_are_processed_in_order_as_normalized_float32_and_keep_timestamp(
    service_config,
) -> None:
    spotter = FakeKeywordSpotter(results=["", "matched"])
    session = _provider(service_config, spotter).create_session()
    _start(session)

    assert session.handle_event(_chunk([0, 16_384], timestamp=101)) is None
    response = session.handle_event(_chunk([-32_768, 32_767], timestamp=202))

    assert isinstance(response, Detection)
    assert response.name == WAKE_WORD_ID
    assert response.timestamp == 202
    assert spotter.decode_count == 2
    received = spotter.streams[0].accepted
    assert [rate for rate, _ in received] == [16_000, 16_000]
    np.testing.assert_allclose(received[0][1], [0.0, 0.5], rtol=0, atol=1e-6)
    np.testing.assert_allclose(
        received[1][1], [-1.0, 32_767 / 32_768], rtol=0, atol=1e-6
    )
    assert session.stream is None
    assert session.on_eof() is None


def test_hit_returns_detection_only_and_does_not_emit_transcript(
    service_config,
) -> None:
    spotter = FakeKeywordSpotter(results=["tivoo-wake"])
    session = _provider(service_config, spotter).create_session()
    _start(session)

    response = session.handle_event(_chunk([100, 200], timestamp=55))

    assert isinstance(response, Detection)
    assert not hasattr(response, "text")
    assert session.on_eof() is None


def test_normal_eof_without_hit_returns_one_not_detected_and_releases_stream(
    service_config,
) -> None:
    spotter = FakeKeywordSpotter()
    session = _provider(service_config, spotter).create_session()
    _start(session)

    response = session.on_eof()

    assert isinstance(response, NotDetected)
    assert session.stream is None
    assert session.on_eof() is None


def test_model_failure_returns_error_and_eof_does_not_emit_not_detected(
    service_config,
) -> None:
    spotter = FakeKeywordSpotter(fail=True)
    session = _provider(service_config, spotter).create_session()
    _start(session)

    response = session.handle_event(_chunk([1, 2], timestamp=1))

    assert isinstance(response, Error)
    assert response.code == "model_error"
    assert session.stream is None
    assert session.on_eof() is None


def test_chunk_format_must_match_audio_start(service_config) -> None:
    spotter = FakeKeywordSpotter()
    session = _provider(service_config, spotter).create_session()
    _start(session)

    response = session.handle_event(
        AudioChunk(
            rate=16_000,
            width=1,
            channels=1,
            audio=b"\x01",
            timestamp=1,
        )
    )

    assert isinstance(response, Error)
    assert response.code == "audio_format"
    assert session.stream is None


def test_cancel_releases_only_its_own_stream_without_not_detected(
    service_config,
) -> None:
    spotter = FakeKeywordSpotter()
    provider = _provider(service_config, spotter)
    first = provider.create_session()
    second = provider.create_session()
    _start(first)
    _start(second)

    first.cancel()

    assert first.stream is None
    assert second.stream is spotter.streams[1]
    assert first.on_eof() is None
    assert second.on_eof().__class__ is NotDetected


def test_audio_chunk_before_start_returns_protocol_error(service_config) -> None:
    session = _provider(service_config, FakeKeywordSpotter()).create_session()
    assert session.handle_event(Detect(names=[WAKE_WORD_ID])) is None

    response = session.handle_event(_chunk([1], timestamp=1))

    assert isinstance(response, Error)
    assert response.code == "invalid_state"
    assert session.stream is None


def test_keyword_generation_uses_official_cli_and_configured_phrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = model_utils.get_model_paths(tmp_path)
    paths.kws_dir.mkdir(parents=True)
    calls: list[list[str]] = []

    monkeypatch.setattr(
        model_utils.shutil, "which", lambda name: "/venv/bin/sherpa-onnx-cli"
    )

    def fake_run(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_text("n ǐ h ǎo @你好_Tivoo\n", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(model_utils.subprocess, "run", fake_run)

    result = model_utils.generate_kws_keywords(tmp_path, "你好 Tivoo")

    assert result == paths.kws_keywords
    assert paths.kws_keywords.read_text(encoding="utf-8") == "n ǐ h ǎo @你好_Tivoo\n"
    assert (
        paths.kws_keywords.with_name("keywords.raw.txt").read_text(encoding="utf-8")
        == "你好 Tivoo @你好_Tivoo\n"
    )
    command = calls[0]
    assert command[:2] == ["/venv/bin/sherpa-onnx-cli", "text2token"]
    assert command[command.index("--tokens-type") + 1] == "phone+ppinyin"
    assert command[command.index("--tokens") + 1] == str(paths.kws_tokens)
    assert command[command.index("--lexicon") + 1] == str(paths.kws_lexicon)


@pytest.mark.parametrize("phrase", ["", "   ", "first\nsecond", "phrase @label"])
def test_keyword_generation_rejects_empty_or_multiline_or_reserved_phrase(
    tmp_path: Path, phrase: str
) -> None:
    with pytest.raises(ValueError):
        model_utils.generate_kws_keywords(tmp_path, phrase)


def test_keyword_generation_explains_unknown_english_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = model_utils.get_model_paths(tmp_path)
    paths.kws_dir.mkdir(parents=True)
    monkeypatch.setattr(
        model_utils.shutil, "which", lambda name: "/venv/bin/sherpa-onnx-cli"
    )

    def skip_unknown_word(command, **kwargs):
        Path(command[-1]).write_text("", encoding="utf-8")
        return SimpleNamespace(
            returncode=0,
            stdout="Word Tivoo not in lexicon and it is not a CJK character.",
            stderr="",
        )

    monkeypatch.setattr(model_utils.subprocess, "run", skip_unknown_word)

    with pytest.raises(model_utils.ModelAssetError, match="English token.*en.phone"):
        model_utils.generate_kws_keywords(tmp_path, "你好 Tivoo")


def test_keyword_generation_fails_when_official_cli_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_utils.shutil, "which", lambda name: None)

    with pytest.raises(model_utils.ModelAssetError, match="sherpa-onnx-cli"):
        model_utils.generate_kws_keywords(tmp_path, "你好 Tivoo")


def test_keyword_generation_does_not_replace_existing_file_when_cli_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = model_utils.get_model_paths(tmp_path)
    paths.kws_dir.mkdir(parents=True)
    paths.kws_keywords.write_text("old @old\n", encoding="utf-8")
    monkeypatch.setattr(
        model_utils.shutil, "which", lambda name: "/venv/bin/sherpa-onnx-cli"
    )

    def fail_run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="unsupported phrase")

    monkeypatch.setattr(model_utils.subprocess, "run", fail_run)

    with pytest.raises(model_utils.ModelAssetError, match="text2token"):
        model_utils.generate_kws_keywords(tmp_path, "你好 Tivoo")

    assert paths.kws_keywords.read_text(encoding="utf-8") == "old @old\n"
