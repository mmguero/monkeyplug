#!/usr/bin/env bash

# create an SQLite3 database and store a unique value in it

set -e
set -u
set -o pipefail
shopt -s nocasematch

ENCODING="utf-8"

# parse command-line options
DATABASE_FILESPEC=""
TABLE_NAME=mesa
FIELD_NAME=campo
OPERATION=""
VALUE=""
while getopts 'v:d:t:f:o:' OPTION; do
    case "$OPTION" in
        v)
          VALUE="$(echo "$OPTARG" | sed "s/'/''/g")"
          ;;

        d)
          DATABASE_FILESPEC="$OPTARG"
          ;;

        t)
          TABLE_NAME="$OPTARG"
          ;;

        f)
          FIELD_NAME="$OPTARG"
          ;;

        o)
          OPERATION="$OPTARG"
          ;;

        ?)
          echo "script usage: $(basename $0) -d database.db -t table -f field -v value -o (set|get)" >&2
          exit 1
          ;;
    esac
done
shift "$(($OPTIND -1))"

# cross-platform GNU gnonsense for core utilities
[[ "$(uname -s)" = 'Darwin' ]] && REALPATH=grealpath || REALPATH=realpath
[[ "$(uname -s)" = 'Darwin' ]] && DIRNAME=gdirname || DIRNAME=dirname
if ! (command -v "$REALPATH" && command -v "$DIRNAME" && command -v sqlite3) > /dev/null; then
    echo "$(basename "${BASH_SOURCE[0]}") requires $REALPATH and $DIRNAME and sqlite3"
    exit 1
fi
SCRIPT_PATH="$($DIRNAME $($REALPATH -e "${BASH_SOURCE[0]}"))"

if ( [[ "$OPERATION" != "set" ]]  && [[ "$OPERATION" != "get" ]] ) || [[ -z "$VALUE" ]]; then
    echo "script usage: $(basename $0) -d database.db -t table -f field -v value -o (set|get)" >&2
    exit 1
fi

# get database filename and directory to use, and specify a lock directory for a singleton
[[ -z "$DATABASE_FILESPEC" ]] && DATABASE_FILESPEC="$SCRIPT_PATH"/database.db
DATABASE_DIR="$($DIRNAME "${DATABASE_FILESPEC}")"

# make sure only one instance of the script
LOCK_DIR="${DATABASE_DIR}/$(basename "$DATABASE_FILESPEC")_lock"
function finish {
    rmdir -- "$LOCK_DIR" || echo "Failed to remove lock directory '$LOCK_DIR'" >&2
}

if mkdir -- "$LOCK_DIR" 2>/dev/null; then
    trap finish EXIT
    ECODE=0
    pushd "$DATABASE_DIR" >/dev/null 2>&1

    if [[ "$OPERATION" == "set" ]]; then
        # store an entry in the database
        sqlite3 "$(basename "$DATABASE_FILESPEC")" <<EOF
CREATE TABLE IF NOT EXISTS \`$TABLE_NAME\` (id INTEGER PRIMARY KEY, timestamp DATE DEFAULT (datetime('now','localtime')), \`$FIELD_NAME\` text UNIQUE);
INSERT INTO \`$TABLE_NAME\` (\`$FIELD_NAME\`) VALUES ('$VALUE') ON CONFLICT(\`$FIELD_NAME\`) DO UPDATE SET timestamp=datetime('now','localtime');
SELECT * FROM \`$TABLE_NAME\` WHERE (\`$FIELD_NAME\` == '$VALUE');
EOF

    else
        # retrieve an entry from the database
        mapfile -t OUTPUT < <(sqlite3 "$(basename "$DATABASE_FILESPEC")" <<EOF
CREATE TABLE IF NOT EXISTS \`$TABLE_NAME\` (id INTEGER PRIMARY KEY, timestamp DATE DEFAULT (datetime('now','localtime')), \`$FIELD_NAME\` text UNIQUE);
SELECT * FROM \`$TABLE_NAME\` WHERE (\`$FIELD_NAME\` == '$VALUE');
EOF
        )
        OUTPUT_COUNT=${#OUTPUT[@]}
        ( [[ -z "$OUTPUT_COUNT" ]] || (( $OUTPUT_COUNT == 0 )) ) && ECODE=1 || printf "%s\n" "${OUTPUT[@]}"
        (( $ECODE == 0 )) || echo "\"$VALUE\" not found" >&2
    fi

    popd >/dev/null 2>&1
    finish
    trap - EXIT
    exit $ECODE

else
  exit 1
fi # singleton lock check
