#!/bin/bash
# Run SWI-Prolog on all .pl files in a directory and print their output.
#
# Usage:
#   bash scripts/run_swipl.sh <case_directory> [--verbose]
#
# Environment variables:
#   TIMEOUT_DURATION: Seconds before timeout (default: 10)
#
# Output format (stdout):
#   For each .pl file: filename, then SWI-Prolog stdout, then on timeout:
#   "Result: timeout"

case_directory="${1:-cases}"
TIMEOUT_DURATION="${TIMEOUT_DURATION:-10}"
VERBOSE=false

if [[ "$*" == *"--verbose"* ]]; then
  VERBOSE=true
fi

trap "exit" SIGINT

for file in "$case_directory"/*.pl; do
  echo "$file"
  if [ "$VERBOSE" = true ]; then
    timeout --signal=TERM --kill-after=2s "$TIMEOUT_DURATION" swipl -q -f "$file" < /dev/null
  else
    timeout --signal=TERM --kill-after=2s "$TIMEOUT_DURATION" swipl -q -f "$file" < /dev/null 2>/dev/null
  fi
  if [ $? -eq 124 ]; then
    echo "Result: timeout"
    echo "Label: -2"
  fi
done
