#!/usr/bin/env bash
# harness/run.sh - Quick CLI runner for the sandbox
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "${DIR}/sandbox.py" "$@"
