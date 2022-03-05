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
    # only process audio files that haven't been cleaned before,
    # based on dropping an empty breadcrumb file in the same location
    OUTFILE="${AUDIOFILE%.*}.mp3"
    if [[ "${OUTFILE}" == "${AUDIOFILE}" ]]; then
      OUTFILE="${AUDIOFILE%.*}_clean.mp3"
      NEW_FILE_EXTENSION=0
    else
      NEW_FILE_EXTENSION=1
    fi
    CLEANED_BREADCRUMB=".cleaned_$(echo "${OUTFILE%.*}" | tr -cd '[:alnum:]._-')"
    if [[ ! -e "${CLEANED_BREADCRUMB}" ]]; then
      # clean the audio file
      echo "Processing \"${AUDIOFILE}\"..." >&2
      ${MONKEYPLUG_BIN} -i "${AUDIOFILE}" -o "${OUTFILE}"
      # if the cleaned audio file exists and is larger than negligible,
      # remove the original file and accept the cleaned one
      if [[ -f "${OUTFILE}" ]]; then
        OUTFILE_SIZE=$(stat -c%s "${OUTFILE}")
        if (( ${OUTFILE_SIZE} > 16000 )); then
          rm -f "${AUDIOFILE}"
          if (( ${NEW_FILE_EXTENSION} == 0 )); then
            mv -f "${OUTFILE}" "${AUDIOFILE}" && touch "${CLEANED_BREADCRUMB}"
          else
            touch "${CLEANED_BREADCRUMB}"
          fi
        fi
      fi
    fi
    popd >/dev/null 2>&1
  fi
done
