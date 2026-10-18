#!/usr/bin/env bash
# A small chain through every variant: does each adapter work at all.
cd "$(dirname "$0")"
for v in "$@"; do
  start=$(date +%s)
  if out=$(./run.sh "$v" workflow --chains 3 --steps 3 --timeout 180 2>&1); then
    echo "$v OK $(( $(date +%s) - start ))s $(echo "$out" | grep -o '{"label": "'$v'-workflow".*}' | tail -1)"
  else
    echo "$v FAIL $(( $(date +%s) - start ))s"; echo "$out" | grep -vE 'warnings.warn|PydanticDeprecated|Container ' | tail -8 | sed 's/^/    /'
  fi
done
