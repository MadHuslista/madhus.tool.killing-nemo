#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
AUTOSTART_DIR="$CONFIG_HOME/autostart"
WRAPPER="$HOME/.local/bin/nemo-window-pruner-autostart"
TEMPLATE="$ROOT/autostart/nemo-window-pruner.desktop.in"
TARGET="$AUTOSTART_DIR/nemo-window-pruner.desktop"

if [[ ! -x "$WRAPPER" ]]; then
  printf 'Installed autostart launcher not found: %s\nRun ./scripts/install.sh first.\n' "$WRAPPER" >&2
  exit 1
fi
install -d "$AUTOSTART_DIR"
# Escape replacement delimiter and ampersands for sed; executable paths with spaces are quoted in Exec=.
escaped_wrapper="${WRAPPER//&/\\&}"
escaped_wrapper="${escaped_wrapper//|/\\|}"
sed "s|@EXEC_PATH@|$escaped_wrapper|g" "$TEMPLATE" >"$TARGET"
chmod 0644 "$TARGET"
printf 'Enabled Cinnamon login autostart: %s\n' "$TARGET"
printf 'The daemon will use your configured dry_run value on next login.\n'
