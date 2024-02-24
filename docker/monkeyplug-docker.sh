#!/usr/bin/env bash

MONKEYPLUG_IMAGE="${MONKEYPLUG_IMAGE:-oci.guero.top/monkeyplug:vosk-small}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-docker}"

DEVICE_ARGS=()
ENV_ARGS=()
if [[ "$MONKEYPLUG_IMAGE" =~ .*"whisper".* ]]; then
  DEVICE_ARGS+=( --gpus )
  DEVICE_ARGS+=( all )
  ENV_ARGS+=( -e )
  ENV_ARGS+=( MONKEYPLUG_MODE=whisper )
  ENV_ARGS+=( -e )
  ENV_ARGS+=( WHISPER_MODEL_NAME=$(echo "$MONKEYPLUG_IMAGE" | sed 's/.*:whisper-//') )
else
  ENV_ARGS+=( -e )
  ENV_ARGS+=( MONKEYPLUG_MODE=vosk )
fi

PUID=$([[ "${CONTAINER_ENGINE}" == "podman" ]] && echo 0 || id -u)
PGID=$([[ "${CONTAINER_ENGINE}" == "podman" ]] && echo 0 || id -g)

# run from directory containing audio file

$CONTAINER_ENGINE run --rm -t \
  "${DEVICE_ARGS[@]}" \
  "${ENV_ARGS[@]}" \
  -u $PUID:$PGID \
  -v "$(realpath "${PWD}"):${PWD}" \
  -w "${PWD}" \
  "$MONKEYPLUG_IMAGE" "$@"
