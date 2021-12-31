#!/usr/bin/env bash

export MONKEYPLUG_IMAGE="${MONKEYPLUG_DOCKER_IMAGE:-ghcr.io/mmguero/monkeyplug:small}"

# run from directory containing audio file

docker run --rm -t \
  -u $(id -u):$(id -g) \
  -v "$(realpath "${PWD}"):${PWD}" \
  -w "${PWD}" \
  "$MONKEYPLUG_IMAGE" "$@"
