#!/usr/bin/env bash

if [[ -n "$VOSK_MODEL_URL" ]]; then
  docker build --build-arg VOSK_MODEL_URL="$VOSK_MODEL_URL" -t ghcr.io/mmguero/monkeyplug:latest .
else
  docker build -t ghcr.io/mmguero/monkeyplug:latest .
fi
