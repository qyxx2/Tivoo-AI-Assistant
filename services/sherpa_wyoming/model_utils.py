from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

KWS_MODEL = "sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
WAKE_WORD_ID = "tivoo-wake"
STT_MODEL = "sherpa-onnx-paraformer-zh-small-2024-03-09"
TTS_MODEL = "matcha-icefall-zh-baker"
DEFAULT_MANIFEST_PATH = Path(__file__).with_name("MODEL_SHA256SUMS")

KWS_FILES = (
    f"kws/{KWS_MODEL}/encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    f"kws/{KWS_MODEL}/decoder-epoch-13-avg-2-chunk-16-left-64.onnx",
    f"kws/{KWS_MODEL}/joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx",
    f"kws/{KWS_MODEL}/tokens.txt",
    f"kws/{KWS_MODEL}/en.phone",
)
STT_FILES = (
    f"stt/{STT_MODEL}/model.int8.onnx",
    f"stt/{STT_MODEL}/tokens.txt",
)
TTS_FILES = (
    f"tts/{TTS_MODEL}/model-steps-3.onnx",
    f"tts/{TTS_MODEL}/tokens.txt",
    f"tts/{TTS_MODEL}/lexicon.txt",
    f"tts/{TTS_MODEL}/phone.fst",
    f"tts/{TTS_MODEL}/date.fst",
    f"tts/{TTS_MODEL}/number.fst",
    "tts/vocos-22khz-univ.onnx",
)
REQUIRED_MODEL_FILES = KWS_FILES + STT_FILES + TTS_FILES
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ModelAssetError(RuntimeError):
    """A required model asset is absent or failed integrity validation."""


@dataclass(frozen=True, slots=True)
class ModelPaths:
    kws_dir: Path
    kws_encoder: Path
    kws_decoder: Path
    kws_joiner: Path
    kws_tokens: Path
    kws_lexicon: Path
    kws_keywords: Path
    stt_dir: Path
    stt_model: Path
    stt_tokens: Path
    tts_dir: Path
    tts_model: Path
    tts_tokens: Path
    tts_lexicon: Path
    tts_phone_fst: Path
    tts_date_fst: Path
    tts_number_fst: Path
    tts_vocoder: Path


def get_model_paths(models_dir: Path) -> ModelPaths:
    root = Path(models_dir)
    kws_dir = root / "kws" / KWS_MODEL
    stt_dir = root / "stt" / STT_MODEL
    tts_dir = root / "tts" / TTS_MODEL
    return ModelPaths(
        kws_dir=kws_dir,
        kws_encoder=kws_dir / Path(KWS_FILES[0]).name,
        kws_decoder=kws_dir / Path(KWS_FILES[1]).name,
        kws_joiner=kws_dir / Path(KWS_FILES[2]).name,
        kws_tokens=kws_dir / "tokens.txt",
        kws_lexicon=kws_dir / "en.phone",
        kws_keywords=kws_dir / "keywords.txt",
        stt_dir=stt_dir,
        stt_model=stt_dir / "model.int8.onnx",
        stt_tokens=stt_dir / "tokens.txt",
        tts_dir=tts_dir,
        tts_model=tts_dir / "model-steps-3.onnx",
        tts_tokens=tts_dir / "tokens.txt",
        tts_lexicon=tts_dir / "lexicon.txt",
        tts_phone_fst=tts_dir / "phone.fst",
        tts_date_fst=tts_dir / "date.fst",
        tts_number_fst=tts_dir / "number.fst",
        tts_vocoder=root / "tts" / "vocos-22khz-univ.onnx",
    )


def _read_manifest(manifest_path: Path) -> dict[str, str]:
    if not manifest_path.is_file():
        raise ModelAssetError(f"SHA-256 manifest is missing: {manifest_path}")

    entries: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2 or not _SHA256_RE.fullmatch(parts[0]):
            raise ModelAssetError(
                f"invalid checksum manifest line {line_number}: {raw_line!r}"
            )
        relative_path = parts[1].lstrip("*").strip()
        if not relative_path or Path(relative_path).is_absolute():
            raise ModelAssetError(
                f"invalid checksum path on line {line_number}: {relative_path!r}"
            )
        if ".." in Path(relative_path).parts:
            raise ModelAssetError(
                f"invalid checksum path on line {line_number}: {relative_path!r}"
            )
        if relative_path in entries:
            raise ModelAssetError(f"duplicate checksum entry for {relative_path}")
        entries[relative_path] = parts[0].lower()
    return entries


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model_files(
    models_dir: Path,
    manifest_path: Path | None = None,
) -> dict[str, Path]:
    """Require and checksum every model file before constructing any model."""

    root = Path(models_dir)
    entries = _read_manifest(manifest_path or DEFAULT_MANIFEST_PATH)
    verified: dict[str, Path] = {}

    for relative_path in REQUIRED_MODEL_FILES:
        expected = entries.get(relative_path)
        if expected is None:
            raise ModelAssetError(
                f"missing SHA-256 entry for required model file: {relative_path}"
            )

        path = root / relative_path
        if not path.is_file():
            raise ModelAssetError(f"required model file is missing: {path}")

        actual = _sha256(path)
        if actual != expected:
            raise ModelAssetError(
                f"SHA-256 mismatch for {relative_path}: "
                f"expected {expected}, got {actual}"
            )
        verified[relative_path] = path

    return verified


def generate_kws_keywords(models_dir: Path, phrase: str) -> Path:
    """Generate the one configured wake keyword with Sherpa's pinned CLI."""

    phrase = phrase.strip()
    if not phrase:
        raise ValueError("WAKE_WORD_PHRASE cannot be blank")
    if any(char in phrase for char in "\r\n@:#"):
        raise ValueError("WAKE_WORD_PHRASE contains text2token-reserved characters")

    paths = get_model_paths(models_dir)
    paths.kws_dir.mkdir(parents=True, exist_ok=True)
    cli_path = shutil.which("sherpa-onnx-cli")
    if cli_path is None:
        raise ModelAssetError("sherpa-onnx-cli is required to generate KWS keywords")

    label = "_".join(phrase.split())
    raw_path = paths.kws_dir / "keywords.raw.txt"
    temporary_path = paths.kws_keywords.with_name("keywords.txt.tmp")
    raw_path.write_text(f"{phrase} @{label}\n", encoding="utf-8")

    command = [
        cli_path,
        "text2token",
        "--tokens",
        str(paths.kws_tokens),
        "--tokens-type",
        "phone+ppinyin",
        "--lexicon",
        str(paths.kws_lexicon),
        str(raw_path),
        str(temporary_path),
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        lines = [
            line.strip()
            for line in temporary_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(lines) != 1 or "@" not in lines[0]:
            cli_output = f"{completed.stdout}\n{completed.stderr}".lower()
            if "not in lexicon" in cli_output:
                raise ModelAssetError(
                    "text2token skipped an English token missing from en.phone; "
                    "add its pronunciation to the KWS lexicon"
                )
            raise ModelAssetError("text2token did not produce exactly one keyword")
        encoded, generated_label = lines[0].rsplit("@", maxsplit=1)
        if not encoded.strip() or generated_label != label:
            raise ModelAssetError(
                "text2token output does not match the configured wake phrase"
            )
        temporary_path.replace(paths.kws_keywords)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise ModelAssetError(
            f"failed to generate KWS keywords with text2token: {detail}"
        ) from exc
    finally:
        temporary_path.unlink(missing_ok=True)

    return paths.kws_keywords
