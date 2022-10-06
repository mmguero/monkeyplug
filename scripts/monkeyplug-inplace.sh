#!/usr/bin/env bash

# use monkeyplug, monkeyplug.py or monkeyplug-docker.sh, if available
MONKEYPLUG_BIN=""
if command -v monkeyplug >/dev/null; then
  MONKEYPLUG_BIN=monkeyplug
elif command -v monkeyplug.py >/dev/null; then
  MONKEYPLUG_BIN=monkeyplug.py
elif command -v monkeyplug-docker.sh >/dev/null; then
  MONKEYPLUG_BIN=monkeyplug-docker.sh
else
  echo "Could not find monkeyplug" >&2
  exit 1
fi

# process arguments as audio files if they exist and have an extension
for AUDIOFILE in "$@"; do
  if [[ -f "${AUDIOFILE}" ]] && [[ "${AUDIOFILE}" == *'.'* ]]; then
    pushd "$(dirname "${AUDIOFILE}")" >/dev/null 2>&1

    # monkeyplug will only process audio files that haven't been cleaned before,
    # based on the contents of embedded metadata tags
    OUTFILE="${AUDIOFILE%.*}_clean.${AUDIOFILE##*.}"
    ${MONKEYPLUG_BIN} -i "${AUDIOFILE}" -o "${OUTFILE}" -x MATCH

    # if the cleaned audio file exists and is larger than negligible,
    # remove the original file and accept the cleaned one. if the output
    # audio file doesn't exist, something went wrong or it didn't need to
    # be cleand
    if [[ -f "${OUTFILE}" ]]; then
      OUTFILE_SIZE=$(stat -c%s "${OUTFILE}")
      if (( ${OUTFILE_SIZE} > 16000 )); then
        rm -f "${AUDIOFILE}"
        mv -f "${OUTFILE}" "${AUDIOFILE}"
      fi
    fi

    popd >/dev/null 2>&1
  fi
done
