#!/usr/bin/env bash

PROCESSES="${MONKEYPLUG_PROCESS_COUNT:-1}"

find . -type f -print0 | xargs -0 -P $PROCESSES -I AUDIO bash -c '
  if ! fuser -s "AUDIO" 2>/dev/null; then
    if file --mime-type "AUDIO" | grep -q ": audio/"; then
      pushd "$(dirname "AUDIO")" >/dev/null 2>&1
      monkeyplug-inplace.sh "$(basename "AUDIO")"
      popd >/dev/null 2>&1
    fi
  fi
'