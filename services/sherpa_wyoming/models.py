from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import sherpa_onnx

from .config import ServiceConfig
from .model_utils import (
    ModelAssetError,
    ModelPaths,
    get_model_paths,
    verify_model_files,
)

_LOGGER = logging.getLogger("tivoo.sherpa_wyoming.models")


class ModelLoadError(RuntimeError):
    """One of the required Sherpa models could not be initialized."""


@dataclass(frozen=True, slots=True)
class ModelBundle:
    """The three service-lifetime model objects, loaded exactly once."""

    keyword_spotter: Any
    stt_recognizer: Any
    tts_engine: Any


def _load_keyword_spotter(
    config: ServiceConfig, paths: ModelPaths
) -> sherpa_onnx.KeywordSpotter:
    if (
        not paths.kws_keywords.is_file()
        or not paths.kws_keywords.read_text(encoding="utf-8").strip()
    ):
        raise ModelAssetError(
            f"KWS keywords file is missing or empty: {paths.kws_keywords}"
        )
    return sherpa_onnx.KeywordSpotter(
        tokens=str(paths.kws_tokens),
        encoder=str(paths.kws_encoder),
        decoder=str(paths.kws_decoder),
        joiner=str(paths.kws_joiner),
        keywords_file=str(paths.kws_keywords),
        num_threads=config.kws_num_threads,
        sample_rate=16_000,
        feature_dim=80,
        keywords_score=config.kws_score,
        keywords_threshold=config.kws_threshold,
        num_trailing_blanks=config.kws_num_trailing_blanks,
        provider="cpu",
    )


def _load_stt_recognizer(
    config: ServiceConfig, paths: ModelPaths
) -> sherpa_onnx.OfflineRecognizer:
    return sherpa_onnx.OfflineRecognizer.from_paraformer(
        paraformer=str(paths.stt_model),
        tokens=str(paths.stt_tokens),
        num_threads=config.stt_num_threads,
        sample_rate=16_000,
        feature_dim=80,
        decoding_method="greedy_search",
        provider="cpu",
    )


def _load_tts_engine(
    config: ServiceConfig, paths: ModelPaths
) -> sherpa_onnx.OfflineTts:
    model_config = sherpa_onnx.OfflineTtsModelConfig(
        matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
            acoustic_model=str(paths.tts_model),
            vocoder=str(paths.tts_vocoder),
            tokens=str(paths.tts_tokens),
            lexicon=str(paths.tts_lexicon),
        ),
        num_threads=config.tts_num_threads,
        provider="cpu",
    )
    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        max_num_sentences=1,
        rule_fsts=",".join(
            (
                str(paths.tts_phone_fst),
                str(paths.tts_date_fst),
                str(paths.tts_number_fst),
            )
        ),
    )
    if not tts_config.validate():
        raise ValueError("Sherpa rejected the Matcha/Vocos TTS model configuration")
    return sherpa_onnx.OfflineTts(tts_config)


def load_models(config: ServiceConfig) -> ModelBundle:
    """Verify every asset first, then initialize the complete model bundle."""

    try:
        verify_model_files(config.models_dir)
    except ModelAssetError as exc:
        raise ModelLoadError(f"Model assets failed validation: {exc}") from exc

    paths = get_model_paths(config.models_dir)
    loaders = (
        ("KWS", _load_keyword_spotter),
        ("STT", _load_stt_recognizer),
        ("TTS", _load_tts_engine),
    )
    loaded: dict[str, Any] = {}
    for name, loader in loaders:
        started = time.perf_counter()
        try:
            loaded[name] = loader(config, paths)
        except Exception as exc:
            _LOGGER.error(
                "model_load_failed model=%s duration_seconds=%.3f error_type=%s",
                name.lower(),
                time.perf_counter() - started,
                type(exc).__name__,
            )
            raise ModelLoadError(f"Failed to initialize {name} model: {exc}") from exc
        _LOGGER.info(
            "model_loaded model=%s duration_seconds=%.3f provider=cpu",
            name.lower(),
            time.perf_counter() - started,
        )

    return ModelBundle(
        keyword_spotter=loaded["KWS"],
        stt_recognizer=loaded["STT"],
        tts_engine=loaded["TTS"],
    )
