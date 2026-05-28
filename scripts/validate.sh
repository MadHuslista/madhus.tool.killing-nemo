#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${1:-$ROOT/config/config.toml}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

printf '== Static unit tests ==\n'
"$PYTHON_BIN" -m unittest discover -s "$ROOT/tests" -v

printf '\n== Runtime prerequisites ==\n'
printf 'XDG_SESSION_TYPE=%s DISPLAY=%s\n' "${XDG_SESSION_TYPE:-unknown}" "${DISPLAY:-unset}"
command -v wmctrl
command -v xprop
wmctrl -m

printf '\n== Nemo WM_CLASS discovery ==\n'
"$PYTHON_BIN" "$ROOT/src/nemo_window_pruner.py" --config "$CONFIG" --discover

printf '\nValidation finished. Dry-run execution command:\n'
printf '  %q %q --config %q --dry-run\n' "$PYTHON_BIN" "$ROOT/src/nemo_window_pruner.py" "$CONFIG"
