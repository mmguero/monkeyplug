#!/usr/bin/env bash

export MONKEYPLUG_IMAGE="${MONKEYPLUG_IMAGE:-oci.guero.top/monkeyplug:small}"
ENGINE="${CONTAINER_ENGINE:-docker}"
if [[ "$ENGINE" == "podman" ]]; then
  CONTAINER_PUID=0
  CONTAINER_PGID=0
else
  CONTAINER_PUID=$(id -u)
  CONTAINER_PGID=$(id -g)
fi

# run from directory containing audio file

$ENGINE run --rm -t \
  -u $CONTAINER_PUID:$CONTAINER_PGID \
  -v "$(realpath "${PWD}"):${PWD}" \
  -w "${PWD}" \
  "$MONKEYPLUG_IMAGE" "$@"
