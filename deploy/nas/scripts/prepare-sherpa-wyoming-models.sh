#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../../.." && pwd)"
MANIFEST="${MODEL_SHA256SUMS:-$REPO_ROOT/services/sherpa_wyoming/MODEL_SHA256SUMS}"
MODELS_DIR="${NAS_MODELS_DIR:-${MODELS_DIR:-}}"

: "${MODELS_DIR:?Set NAS_MODELS_DIR to the persistent model directory}"
[[ -f "$MANIFEST" ]] || { echo "Missing model manifest: $MANIFEST" >&2; exit 1; }

for command_name in curl tar sha256sum awk find; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Required command is unavailable: $command_name" >&2
    exit 1
  }
done

KWS_MODEL="sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
STT_MODEL="sherpa-onnx-paraformer-zh-small-2024-03-09"
TTS_MODEL="matcha-icefall-zh-baker"
KWS_ARCHIVE_SHA256="68447f4fbc67e70eee3a93961f36e81e98f47aef73ce7e7ca00885c6cd3616a"

KWS_FILES=(
  "kws/$KWS_MODEL/encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx"
  "kws/$KWS_MODEL/decoder-epoch-13-avg-2-chunk-16-left-64.onnx"
  "kws/$KWS_MODEL/joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx"
  "kws/$KWS_MODEL/tokens.txt"
  "kws/$KWS_MODEL/en.phone"
)
STT_FILES=(
  "stt/$STT_MODEL/model.int8.onnx"
  "stt/$STT_MODEL/tokens.txt"
)
TTS_FILES=(
  "tts/$TTS_MODEL/model-steps-3.onnx"
  "tts/$TTS_MODEL/tokens.txt"
  "tts/$TTS_MODEL/lexicon.txt"
  "tts/$TTS_MODEL/phone.fst"
  "tts/$TTS_MODEL/date.fst"
  "tts/$TTS_MODEL/number.fst"
)
VOCOS_FILE="tts/vocos-22khz-univ.onnx"

KWS_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/$KWS_MODEL.tar.bz2"
STT_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/$STT_MODEL.tar.bz2"
TTS_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/$TTS_MODEL.tar.bz2"
VOCOS_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos-22khz-univ.onnx"

mkdir -p "$MODELS_DIR"
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tivoo-sherpa-models.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

manifest_hash() {
  awk -v wanted="$1" '
    $1 !~ /^#/ && $2 == wanted { print $1; found = 1; exit }
    END { if (!found) exit 1 }
  ' "$MANIFEST"
}

verify_asset() {
  local file="$1" relative_path="$2"
  local expected actual

  expected="$(manifest_hash "$relative_path")" || {
    echo "Missing SHA-256 entry: $relative_path" >&2
    return 1
  }
  [[ -f "$file" ]] || {
    echo "Required asset is missing: $file" >&2
    return 1
  }
  actual="$(sha256sum "$file" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || {
    echo "SHA-256 mismatch for $relative_path" >&2
    return 1
  }
}

# Existing files are validated before downloads. Invalid files are never replaced.
ALL_FILES=("${KWS_FILES[@]}" "${STT_FILES[@]}" "${TTS_FILES[@]}" "$VOCOS_FILE")
for relative_path in "${ALL_FILES[@]}"; do
  target="$MODELS_DIR/$relative_path"
  if [[ -e "$target" || -L "$target" ]]; then
    verify_asset "$target" "$relative_path" || {
      echo "Existing asset is invalid; refusing to overwrite it: $target" >&2
      exit 1
    }
  fi
done

download_archive() {
  local label="$1" url="$2" archive_sha="$3" extract_dir="$4"
  shift 4
  local -a files=("$@")
  local needs_download=0
  local relative_path target archive actual_sha base_name staged
  local -a matches=()

  for relative_path in "${files[@]}"; do
    target="$MODELS_DIR/$relative_path"
    [[ -f "$target" ]] || needs_download=1
  done

  if (( needs_download == 0 )); then
    echo "$label: all assets already present"
    return
  fi

  archive="$TEMP_DIR/$label.tar.bz2"
  echo "$label: downloading missing model assets"
  curl --fail --location --retry 2 --connect-timeout 20 --max-time 900 \
    --output "$archive" "$url"

  if [[ -n "$archive_sha" ]]; then
    actual_sha="$(sha256sum "$archive" | awk '{print $1}')"
    [[ "$actual_sha" == "$archive_sha" ]] || {
      echo "$label archive SHA-256 mismatch" >&2
      return 1
    }
  fi

  mkdir -p "$extract_dir"
  tar -xjf "$archive" -C "$extract_dir"

  for relative_path in "${files[@]}"; do
    target="$MODELS_DIR/$relative_path"
    [[ -f "$target" ]] && continue

    base_name="${relative_path##*/}"
    mapfile -t matches < <(find "$extract_dir" -type f -name "$base_name" -print)
    (( ${#matches[@]} == 1 )) || {
      echo "$label archive did not contain one unambiguous $base_name" >&2
      return 1
    }

    verify_asset "${matches[0]}" "$relative_path"
    mkdir -p "$(dirname "$target")"
    staged="$target.tmp.$$"
    cp -- "${matches[0]}" "$staged"
    if [[ -e "$target" ]]; then
      verify_asset "$target" "$relative_path"
      rm -f -- "$staged"
    else
      mv -- "$staged" "$target"
    fi
    verify_asset "$target" "$relative_path"
  done
}

download_archive "kws" "$KWS_URL" "$KWS_ARCHIVE_SHA256" \
  "$TEMP_DIR/kws" "${KWS_FILES[@]}"
download_archive "stt" "$STT_URL" "" "$TEMP_DIR/stt" "${STT_FILES[@]}"
download_archive "tts" "$TTS_URL" "" "$TEMP_DIR/tts" "${TTS_FILES[@]}"

if [[ ! -f "$MODELS_DIR/$VOCOS_FILE" ]]; then
  echo "vocos: downloading missing model asset"
  vocos_tmp="$TEMP_DIR/vocos-22khz-univ.onnx"
  curl --fail --location --retry 2 --connect-timeout 20 --max-time 900 \
    --output "$vocos_tmp" "$VOCOS_URL"
  verify_asset "$vocos_tmp" "$VOCOS_FILE"
  mkdir -p "$(dirname "$MODELS_DIR/$VOCOS_FILE")"
  cp -- "$vocos_tmp" "$MODELS_DIR/$VOCOS_FILE.tmp.$$"
  mv -- "$MODELS_DIR/$VOCOS_FILE.tmp.$$" "$MODELS_DIR/$VOCOS_FILE"
fi

(
  cd "$MODELS_DIR"
  sha256sum --check "$MANIFEST"
)
echo "Model preparation complete: all required P7A model assets match MODEL_SHA256SUMS."
