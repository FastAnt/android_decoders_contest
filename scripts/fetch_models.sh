#!/usr/bin/env bash
# Download the exact runtime model files used by the Android client.
#
# The models are not stored in Git. They are published as GitHub Release
# assets under the licenses documented in WEIGHTS.md and LICENSES/.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${MODEL_BASE_URL:-https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1}"

fetch() {
  local asset="$1"
  local dest="$2"
  local sha="$3"

  mkdir -p "$(dirname "$dest")"
  if [[ -f "$dest" ]] && echo "$sha  $dest" | sha256sum -c - >/dev/null 2>&1; then
    echo "ok: $dest"
    return
  fi

  echo "download: $BASE_URL/$asset"
  curl -fL --retry 3 --retry-delay 2 --output "$dest" "$BASE_URL/$asset"
  echo "$sha  $dest" | sha256sum -c -
}

fetch \
  "sage_r128_dec_w8a8.tflite" \
  "$ROOT/client_android/assets/sage/dec_w8a8.tflite" \
  "d173b21e34b12e4be163741918bbd56870e16464f3d6d8592659d1855e88daa4"

fetch \
  "same_s_s128_dec_w8a8.tflite" \
  "$ROOT/client_android/assets/same/dec_w8a8_s128.tflite" \
  "7802697d21c67968974c117626da42e55bf0dd250126e0be9a4cfe86245e0ef6"

echo "models ready"
