#!/usr/bin/env bash

[[ "$(uname -s)" = 'Darwin' ]] && REALPATH=grealpath || REALPATH=realpath
[[ "$(uname -s)" = 'Darwin' ]] && DIRNAME=gdirname || DIRNAME=dirname
if ! (type "$REALPATH" && type "$DIRNAME") > /dev/null; then
  echo "$(basename "${BASH_SOURCE[0]}") requires $REALPATH and $DIRNAME"
  exit 1
fi
SCRIPT_PATH="$($DIRNAME $($REALPATH -e "${BASH_SOURCE[0]}"))"
STORE_UNIQUE_SCRIPT="$SCRIPT_PATH"/store_unique.sh

ENCODING="utf-8"

# parse command-line options
DATABASE_FILESPEC="$SCRIPT_PATH"/monkeyplug.db
while getopts 'd:' OPTION; do
    case "$OPTION" in
        d)
          DATABASE_FILESPEC="$OPTARG"
          ;;

        ?)
          echo "script usage: $(basename $0) -d database.db" >&2
          exit 1
          ;;
    esac
done
shift "$(($OPTIND -1))"

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

    # we'll use an sqlite database to keep track of scrubbed files, it's faster
    # than actually checking the file itself
    if [[ -x "$STORE_UNIQUE_SCRIPT" ]] && [[ -n "$DATABASE_FILESPEC" ]]; then
      "$STORE_UNIQUE_SCRIPT" \
        -d "$DATABASE_FILESPEC" \
        -t "episode" \
        -f "filename" \
        -v "$(basename "$AUDIOFILE")" \
        -o get
      GET_RESULT=$?
    else
      GET_RESULT=1
    fi

    # continue processing as long as we didn't find the filename in the database
    if [[ "$GET_RESULT" -ne "0" ]]; then

      # monkeyplug will only process audio files that haven't been cleaned before,
      # based on the contents of embedded metadata tags
      OUTFILE="${AUDIOFILE%.*}_clean.${AUDIOFILE##*.}"
      ${MONKEYPLUG_BIN} -i "${AUDIOFILE}" -o "${OUTFILE}" -x MATCH --pad-milliseconds-pre 50

      # if the cleaned audio file exists and is larger than negligible,
      # remove the original file and accept the cleaned one. if the output
      # audio file doesn't exist, something went wrong or it didn't need to be cleand
      if [[ -f "${OUTFILE}" ]]; then
        OUTFILE_SIZE=$(stat -c%s "${OUTFILE}")
        if (( ${OUTFILE_SIZE} > 16000 )); then
          rm -f "${AUDIOFILE}"
          mv -f "${OUTFILE}" "${AUDIOFILE}"
        fi

        # store the resultant file in the database so we don't process it again
        if [[ -x "$STORE_UNIQUE_SCRIPT" ]] && [[ -n "$DATABASE_FILESPEC" ]]; then
          "$STORE_UNIQUE_SCRIPT" \
            -d "$DATABASE_FILESPEC" \
            -t "episode" \
            -f "filename" \
            -v "$(basename "$AUDIOFILE")" \
            -o set
        fi

      fi # OUTFILE exists
    fi # database check
    popd >/dev/null 2>&1
  fi # input audio file exists
done
