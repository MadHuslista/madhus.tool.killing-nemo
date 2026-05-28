#!/usr/bin/env bash
set -euo pipefail
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN="$HOME/.local/bin/nemo-window-pruner"
AUTOSTART_BIN="$HOME/.local/bin/nemo-window-pruner-autostart"
AUTOSTART="$CONFIG_HOME/autostart/nemo-window-pruner.desktop"
DOC="$HOME/.local/share/doc/nemo-window-pruner"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/nemo-window-pruner"

rm -f "$AUTOSTART" "$BIN" "$AUTOSTART_BIN"
rm -rf "$DOC"
printf 'Removed binary, documentation, and autostart entry.\n'
printf 'Preserved configuration: %s/nemo-window-pruner/config.toml\n' "$CONFIG_HOME"
printf 'Preserved logs/state: %s\n' "$STATE"
printf 'Remove preserved data manually only if no longer needed.\n'
