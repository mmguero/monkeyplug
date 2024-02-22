#!/usr/bin/env bash

set -e
set -o pipefail

ENCODING="utf-8"

ENGINE="${CONTAINER_ENGINE:-docker}"

[[ "$(uname -s)" = 'Darwin' ]] && REALPATH=grealpath || REALPATH=realpath
[[ "$(uname -s)" = 'Darwin' ]] && DIRNAME=gdirname || DIRNAME=dirname
if ! (type "$REALPATH" && type "$DIRNAME" && type "$ENGINE") > /dev/null; then
  echo "$(basename "${BASH_SOURCE[0]}") requires $ENGINE, $REALPATH and $DIRNAME"
  exit 1
fi
export SCRIPT_PATH="$($DIRNAME $($REALPATH -e "${BASH_SOURCE[0]}"))"

pushd "$SCRIPT_PATH"/.. >/dev/null 2>&1

BUILD_ARGS=()
if [[ -n "$VOSK_MODEL_URL" ]]; then
  BUILD_ARGS+=( --build-arg )
  BUILD_ARGS+=( VOSK_MODEL_URL="$VOSK_MODEL_URL" )
fi
if [[ -n "$WHISPER_MODEL_NAME" ]]; then
  BUILD_ARGS+=( --build-arg )
  BUILD_ARGS+=( WHISPER_MODEL_NAME="$WHISPER_MODEL_NAME" )
fi

$ENGINE build -f docker/Dockerfile "${BUILD_ARGS[@]}" -t oci.guero.top/monkeyplug .



popd >/dev/null 2>&1