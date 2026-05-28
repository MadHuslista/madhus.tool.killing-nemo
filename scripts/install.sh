#!/usr/bin/env bash
set -euo pipefail

ENABLE_AUTOSTART=false
case "${1:-}" in
  "") ;;
  --enable-autostart) ENABLE_AUTOSTART=true ;;
  *) printf 'Usage: %s [--enable-autostart]\n' "$0" >&2; exit 2 ;;
esac

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
BIN_DIR="$HOME/.local/bin"
DOC_DIR="$HOME/.local/share/doc/nemo-window-pruner"
AUTOSTART_DIR="$CONFIG_HOME/autostart"
CONFIG_DIR="$CONFIG_HOME/nemo-window-pruner"

missing=()
command -v python3 >/dev/null 2>&1 || missing+=(python3)
command -v wmctrl >/dev/null 2>&1 || missing+=(wmctrl)
command -v xprop >/dev/null 2>&1 || missing+=(xprop)
if ((${#missing[@]})); then
  printf 'Missing command(s): %s\n' "${missing[*]}" >&2
  printf 'On Linux Mint, install prerequisites with:\n  sudo apt install python3 wmctrl x11-utils\n' >&2
  exit 1
fi
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("Python >= 3.11 is required because the script uses stdlib tomllib.")
PY

install -d "$BIN_DIR" "$CONFIG_DIR" "$STATE_HOME/nemo-window-pruner" "$DOC_DIR"
install -m 0755 "$ROOT/src/nemo_window_pruner.py" "$BIN_DIR/nemo-window-pruner"
install -m 0755 "$ROOT/scripts/nemo-window-pruner-autostart.sh" "$BIN_DIR/nemo-window-pruner-autostart"
if [[ ! -e "$CONFIG_DIR/config.toml" ]]; then
  install -m 0644 "$ROOT/config/config.toml" "$CONFIG_DIR/config.toml"
  printf 'Installed new safe configuration: %s (dry_run=true)\n' "$CONFIG_DIR/config.toml"
else
  printf 'Preserved existing configuration: %s\n' "$CONFIG_DIR/config.toml"
fi
install -m 0644 "$ROOT/README.md" "$DOC_DIR/README.md"

if "$ENABLE_AUTOSTART"; then
  "$ROOT/scripts/enable-autostart.sh"
else
  printf 'Autostart not enabled. After dry-run validation, enable with:\n'
  printf '  %s/scripts/enable-autostart.sh\n' "$ROOT"
fi

printf '\nInstalled binary: %s/nemo-window-pruner\n' "$BIN_DIR"
printf 'Next step: nemo-window-pruner --config "%s/config.toml" --discover\n' "$CONFIG_DIR"
