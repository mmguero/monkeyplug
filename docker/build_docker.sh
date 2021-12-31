#!/usr/bin/env bash

set -e
set -o pipefail

ENCODING="utf-8"

[[ "$(uname -s)" = 'Darwin' ]] && REALPATH=grealpath || REALPATH=realpath
[[ "$(uname -s)" = 'Darwin' ]] && DIRNAME=gdirname || DIRNAME=dirname
if ! (type "$REALPATH" && type "$DIRNAME" && type docker) > /dev/null; then
  echo "$(basename "${BASH_SOURCE[0]}") requires docker, $REALPATH and $DIRNAME"
  exit 1
fi
export SCRIPT_PATH="$($DIRNAME $($REALPATH -e "${BASH_SOURCE[0]}"))"

pushd "$SCRIPT_PATH"/.. >/dev/null 2>&1

if [[ -n "$VOSK_MODEL_URL" ]]; then
  docker build -f docker/Dockerfile --build-arg VOSK_MODEL_URL="$VOSK_MODEL_URL" -t ghcr.io/mmguero/monkeyplug .
else
  docker build -f docker/Dockerfile -t ghcr.io/mmguero/monkeyplug:small .
fi

popd >/dev/null 2>&1