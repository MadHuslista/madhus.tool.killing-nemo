#!/usr/bin/env bash
set -euo pipefail
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_DIR="$STATE_HOME/nemo-window-pruner"
mkdir -p "$STATE_DIR"
exec "$HOME/.local/bin/nemo-window-pruner" \
  --config "$CONFIG_HOME/nemo-window-pruner/config.toml" \
  >> "$STATE_DIR/autostart.log" 2>&1
