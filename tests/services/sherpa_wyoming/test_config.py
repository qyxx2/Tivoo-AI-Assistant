from pathlib import Path

import pytest
from sherpa_wyoming.config import ServiceConfig, load_config


def test_load_config_uses_contract_defaults() -> None:
    config = load_config({"WAKE_WORD_PHRASE": "Hi Tivoo"})

    assert isinstance(config, ServiceConfig)
    assert config.host == "0.0.0.0"
    assert config.port == 10400
    assert config.models_dir == Path("/models")
    assert config.wake_word_phrase == "Hi Tivoo"
    assert config.kws_num_threads == 1
    assert config.kws_score == 1.0
    assert config.kws_threshold == 0.25
    assert config.kws_num_trailing_blanks == 1
    assert config.stt_num_threads == 2
    assert config.stt_max_seconds == 300
    assert config.stt_max_bytes == 9_600_000
    assert config.tts_num_threads == 1
    assert config.tts_max_sentence_chars == 80
    assert config.tts_queue_bytes == 131_072
    assert config.tts_chunk_bytes == 4_096
    assert config.max_pending_per_model == 1


@pytest.mark.parametrize("phrase", [None, "", " \t "])
def test_load_config_requires_nonblank_wake_word_phrase(
    phrase: str | None,
) -> None:
    environ = {} if phrase is None else {"WAKE_WORD_PHRASE": phrase}

    with pytest.raises(ValueError, match="WAKE_WORD_PHRASE"):
        load_config(environ)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"HOST": "  "}, "HOST"),
        ({"PORT": "0"}, "PORT"),
        ({"PORT": "65536"}, "PORT"),
        ({"PORT": "not-a-number"}, "PORT"),
        ({"MODELS_DIR": " "}, "MODELS_DIR"),
        ({"KWS_NUM_THREADS": "0"}, "KWS_NUM_THREADS"),
        ({"KWS_SCORE": "-0.1"}, "KWS_SCORE"),
        ({"KWS_SCORE": "nan"}, "KWS_SCORE"),
        ({"KWS_SCORE": "inf"}, "KWS_SCORE"),
        ({"KWS_THRESHOLD": "-0.1"}, "KWS_THRESHOLD"),
        ({"KWS_THRESHOLD": "1.01"}, "KWS_THRESHOLD"),
        ({"KWS_NUM_TRAILING_BLANKS": "-1"}, "KWS_NUM_TRAILING_BLANKS"),
        ({"STT_NUM_THREADS": "0"}, "STT_NUM_THREADS"),
        ({"STT_MAX_SECONDS": "0"}, "STT_MAX_SECONDS"),
        ({"STT_MAX_BYTES": "-1"}, "STT_MAX_BYTES"),
        ({"TTS_NUM_THREADS": "0"}, "TTS_NUM_THREADS"),
        ({"TTS_MAX_SENTENCE_CHARS": "0"}, "TTS_MAX_SENTENCE_CHARS"),
        ({"TTS_QUEUE_BYTES": "0"}, "TTS_QUEUE_BYTES"),
        ({"TTS_QUEUE_BYTES": "131073"}, "TTS_QUEUE_BYTES"),
        ({"TTS_CHUNK_BYTES": "0"}, "TTS_CHUNK_BYTES"),
        ({"TTS_CHUNK_BYTES": "4097"}, "TTS_CHUNK_BYTES"),
        (
            {"TTS_QUEUE_BYTES": "2048", "TTS_CHUNK_BYTES": "4096"},
            "TTS_CHUNK_BYTES",
        ),
        ({"MAX_PENDING_PER_MODEL": "0"}, "MAX_PENDING_PER_MODEL"),
    ],
)
def test_load_config_rejects_invalid_values(
    overrides: dict[str, str], message: str
) -> None:
    environ = {"WAKE_WORD_PHRASE": "Hi Tivoo", **overrides}

    with pytest.raises(ValueError, match=message):
        load_config(environ)


def test_load_config_returns_immutable_config() -> None:
    config = load_config({"WAKE_WORD_PHRASE": "Hi Tivoo"})

    with pytest.raises(AttributeError):
        config.port = 9999  # type: ignore[misc]
