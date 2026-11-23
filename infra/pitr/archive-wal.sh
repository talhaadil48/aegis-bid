#!/bin/bash
set -euo pipefail
[[ "$2" =~ ^[A-Za-z0-9_.-]+$ ]] && [[ "$2" != *..* ]] || exit 1
target="/wal/$2"
if [[ -e "$target" ]]; then
  cmp -- "$1" "$target"
  exit $?
fi
temporary="/wal/.${2}.tmp.$$"
trap 'rm -f -- "$temporary"' EXIT
cp -- "$1" "$temporary"
sync -f "$temporary"
# Hard-link publishes atomically without overwriting an existing archived segment.
if ! ln -- "$temporary" "$target"; then cmp -- "$1" "$target"; fi
sync -f /wal
