# Nemo Window Pruner — Proof of Concept v0.1

A small, reversible X11 daemon for Linux Mint/Cinnamon that limits **Nemo file-manager windows** using a safe least-recently-used policy: when too many Nemo windows remain open, it may gracefully close only an old, unfocused, inactive window.

## 0. Executive summary

### Recommendation

Use this PoC in **dry-run mode first**. It is intentionally conservative and starts with `dry_run = true`; no window is closed until you explicitly change that setting or invoke `--live`.

### Default policy

| Control | v0.1 default | Purpose |
|---|---:|---|
| Scope | Current workspace only | Avoid affecting context on other workspaces |
| Maximum Nemo windows | 5 | Retain a bounded active working set |
| Minimum inactivity before eligible close | 30 minutes | Avoid pruning recently used directories |
| Startup grace period | 30 minutes | Focus history before daemon launch is unknown |
| Focused window | Always protected | Never close the window currently being used |
| Closures per poll cycle | 1 maximum | Prevent cascaded destructive behavior |
| Execution mode | Dry run | Log candidate actions without closing anything |

### What this PoC is and is not

**Implemented:** an X11/Cinnamon-oriented user-space daemon that discovers normal Nemo windows by exact `WM_CLASS`, observes focus through the standardized EWMH active-window property, and sends a normal window-close request for the least-recently-focused eligible window.

**Not implemented:** Wayland support, GUI configuration, persistence of focus history across restarts, undo/reopen of closed directory locations, or a Cinnamon extension UI.

### Safety status

- [Known] It never intentionally closes the focused Nemo window.
- [Known] It matches only exact `nemo.Nemo` windows by default; `nemo-desktop` does not match.
- [Known] It defaults to dry-run mode and one candidate per cycle.
- [Could be known on your machine] The exact Nemo `WM_CLASS`; the provided discovery command confirms it before live mode.
- [Cannot be known before observing your workflow] Whether automatic pruning is genuinely helpful rather than disruptive; use dry-run logs to decide.

---

## 1. Quick start: safe validation workflow

### 1.1 Prerequisites

This v0.1 is designed for your **Linux Mint/Cinnamon X11** desktop. Confirm the session type:

```bash
printf 'session=%s display=%s\n' "${XDG_SESSION_TYPE:-unknown}" "${DISPLAY:-unset}"
```

Expected result includes `session=x11`. If it reports `wayland`, do not enable live mode: this PoC relies on X11/EWMH window inspection and control.

Install runtime dependencies:

```bash
sudo apt update
sudo apt install python3 wmctrl x11-utils
```

`xprop` is supplied by `x11-utils`; Python 3.11 or newer is required because configuration uses the standard-library TOML parser.

### 1.2 Install the tool without enabling autostart

From the unpacked project directory:

```bash
chmod +x scripts/*.sh src/nemo_window_pruner.py
./scripts/install.sh
```

This installs:

```text
~/.local/bin/nemo-window-pruner
~/.local/bin/nemo-window-pruner-autostart
~/.config/nemo-window-pruner/config.toml
~/.local/share/doc/nemo-window-pruner/README.md
```

It does **not** automatically enable startup execution.

### 1.3 Confirm Nemo window identification

Open at least two ordinary Nemo file-manager windows, then run:

```bash
nemo-window-pruner \
  --config ~/.config/nemo-window-pruner/config.toml \
  --discover
```

Expected output contains entries such as:

```text
MATCH id=0x... desktop=... WM_CLASS=nemo.Nemo title='... - File Manager'
```

If the windows appear as `NOT_MATCH`, edit these fields in the configuration to exactly match the reported class:

```toml
[matching]
wm_class_instance = "nemo"
wm_class_name = "Nemo"
```

### 1.4 Run in foreground dry-run mode

Run this from a terminal and keep using Nemo normally:

```bash
nemo-window-pruner \
  --config ~/.config/nemo-window-pruner/config.toml \
  --dry-run
```

Because the initial configuration is conservative, a candidate is logged only when all conditions are true:

1. More than five matching Nemo windows exist on the current workspace.
2. The candidate is not focused.
3. The daemon has observed it for at least 30 minutes.
4. It has not been focused for at least 30 minutes.

A candidate action appears as:

```text
INFO nemo-window-pruner: WOULD_CLOSE id=0x... desktop=0 inactive=... title='...'
```

Stop the foreground process with `Ctrl+C`.

### 1.5 Fast deliberate dry-run test

To validate behavior without waiting 30 minutes, keep at least three Nemo windows open and run:

```bash
nemo-window-pruner \
  --config ~/.config/nemo-window-pruner/config.toml \
  --dry-run \
  --max-windows 2 \
  --min-inactive-minutes 0 \
  --startup-grace-minutes 0
```

Switch focus among your Nemo windows. Once three are visible to the policy, it should log `WOULD_CLOSE` for the least-recently-focused non-active window. It still closes nothing.

### 1.6 Enable live mode only after reviewing the dry-run behavior

Option A — one foreground live experiment, without editing the configuration:

```bash
nemo-window-pruner \
  --config ~/.config/nemo-window-pruner/config.toml \
  --live
```

Option B — persistent behavior: edit the configuration:

```bash
nano ~/.config/nemo-window-pruner/config.toml
```

Change only:

```toml
dry_run = false
```

Keep the conservative inactivity and startup-grace settings during the first persistent run.

### 1.7 Enable start-on-login after live validation

The primary startup method for v0.1 is a Cinnamon autostart entry because it runs after a graphical login and reliably inherits the X11 display context:

```bash
./scripts/enable-autostart.sh
```

Alternatively, install and enable autostart in one step from a clean installation:

```bash
./scripts/install.sh --enable-autostart
```

On the next Cinnamon login, log output is written to:

```text
~/.local/state/nemo-window-pruner/autostart.log
```

Inspect it with:

```bash
tail -f ~/.local/state/nemo-window-pruner/autostart.log
```

---

## 2. What the implementation does

### 2.1 Policy mechanics

Each polling cycle performs this sequence:

1. `wmctrl -lx` enumerates X11 windows and their `WM_CLASS`.
2. Only windows whose class exactly matches `nemo.Nemo` are eligible by default.
3. `wmctrl -d` identifies the current workspace when `scope = "current_workspace"`.
4. `xprop -root _NET_ACTIVE_WINDOW` retrieves the focused window identifier.
5. The daemon updates last-focused timestamps only for observed Nemo windows.
6. If window count exceeds the configured limit, it selects the oldest eligible inactive window.
7. Dry-run logs `WOULD_CLOSE`; live mode sends `wmctrl -i -c <window-id>`.

### 2.2 Why it closes a window rather than terminating Nemo

Nemo exposes `--quit`, but that exits Nemo broadly rather than selecting a single stale window. The daemon instead asks the X11 window manager to close one specific managed window using a standard close request. This preserves other Nemo windows and does not issue a process kill.

### 2.3 Why this is an X11 tool rather than a Nemo plugin

The desired policy concerns top-level application windows, focus ordering, and workspaces. Those are window-manager concepts, not directory-view actions. Nemo actions and extensions are appropriate for file-manager content operations; this PoC operates at the EWMH/X11 window layer.

---

## 3. Files included

```text
nemo-window-pruner-poc-v0.1/
├── README.md
├── src/
│   └── nemo_window_pruner.py         # standalone daemon and CLI
├── config/
│   └── config.toml                   # safe default configuration
├── autostart/
│   └── nemo-window-pruner.desktop.in # Cinnamon startup template, generated on install
├── systemd/
│   └── nemo-window-pruner.service    # optional advanced startup route
├── scripts/
│   ├── install.sh                    # install binary/config/docs; optional autostart
│   ├── enable-autostart.sh           # safely render/start Cinnamon login entry
│   ├── nemo-window-pruner-autostart.sh # launcher with log redirection
│   ├── uninstall.sh                  # remove executable/autostart; preserve data
│   └── validate.sh                   # tests + desktop discovery validation
└── tests/
    └── test_nemo_window_pruner.py    # deterministic parser/policy unit tests
```

---

## 4. Configuration reference

Configuration file after installation:

```text
~/.config/nemo-window-pruner/config.toml
```

| Key | Type | Default | Operational effect | Risk when changed |
|---|---|---:|---|---|
| `policy.max_windows` | integer | `5` | Number of retained Nemo windows in scope | Too low increases unwanted closures |
| `policy.min_inactive_minutes` | float | `30.0` | Required time since last observed focus | `0` enables immediate pruning after grace |
| `policy.startup_grace_minutes` | float | `30.0` | Protects windows whose earlier activity is unknown | `0` may prune old windows immediately after launch |
| `policy.poll_interval_seconds` | float | `2.0` | Observation cadence | Very low values add unnecessary polling |
| `policy.max_closes_per_cycle` | integer | `1` | Closure rate limiter | Higher values can prune several windows rapidly |
| `policy.protect_focused_window` | boolean | `true` | Excludes active window | Keep `true` |
| `policy.scope` | enum | `"current_workspace"` | Limits counted/closed windows | `"all_workspaces"` can disturb hidden contexts |
| `policy.dry_run` | boolean | `true` | When true, only log candidate closures | `false` performs closure requests |
| `matching.wm_class_instance` | string | `"nemo"` | Exact application-instance match | Wrong value means no detection or wrong matching |
| `matching.wm_class_name` | string | `"Nemo"` | Exact application-class match | Confirm through `--discover` |
| `logging.level` | string | `"INFO"` | Logging verbosity | Use `DEBUG` only for diagnosis |

### Suggested policy after a successful trial

Do not change multiple controls simultaneously. Begin by enabling live mode with defaults:

```toml
[policy]
max_windows = 5
min_inactive_minutes = 30.0
startup_grace_minutes = 30.0
scope = "current_workspace"
dry_run = false
```

After several normal work sessions, lower `max_windows` or reduce inactivity only if the logs show the retained working set is larger than needed.

---

## 5. Validation and operation

### 5.1 Run static tests and desktop discovery together

From the unpacked project directory:

```bash
./scripts/validate.sh
```

The static tests verify:

- Nemo exact-class filtering excludes a `nemo-desktop` class.
- Window identifiers are normalized consistently.
- Current-workspace parsing works.
- No closure occurs at or under the configured limit.
- Least-recently-focused selection excludes the active window.
- Startup grace blocks immediate closure.

The runtime portion validates dependencies and reports actual Nemo `WM_CLASS` entries from your desktop.

### 5.2 Review live/autostart logs

```bash
tail -n 100 ~/.local/state/nemo-window-pruner/autostart.log
```

Action labels:

| Log action | Meaning |
|---|---|
| `WOULD_CLOSE` | Dry-run candidate; no operation occurred |
| `CLOSE` | Live mode issued a normal close request to that window |
| `Cycle failed` | Inspection or close command failed; review dependency/display state |

### 5.3 Temporarily disable start-on-login

```bash
mv ~/.config/autostart/nemo-window-pruner.desktop \
   ~/.config/autostart/nemo-window-pruner.desktop.disabled
```

Re-enable it with:

```bash
mv ~/.config/autostart/nemo-window-pruner.desktop.disabled \
   ~/.config/autostart/nemo-window-pruner.desktop
```

### 5.4 Uninstall

From the extracted package directory:

```bash
./scripts/uninstall.sh
```

The uninstall script removes the executable, installed documentation, and autostart entry, but intentionally preserves the configuration and logs for audit or later reinstall. To remove them manually:

```bash
rm -rf ~/.config/nemo-window-pruner ~/.local/state/nemo-window-pruner
```

---

## 6. Optional `systemd --user` startup route

The `systemd/nemo-window-pruner.service` unit is included for advanced use, but Cinnamon autostart is the recommended v0.1 route because the tool requires the active graphical/X11 session environment.

To use the service instead of XDG autostart:

```bash
mkdir -p ~/.config/systemd/user
install -Dm644 systemd/nemo-window-pruner.service \
  ~/.config/systemd/user/nemo-window-pruner.service
systemctl --user import-environment DISPLAY XAUTHORITY XDG_SESSION_TYPE
systemctl --user daemon-reload
systemctl --user enable --now nemo-window-pruner.service
journalctl --user -u nemo-window-pruner.service -f
```

Disable it with:

```bash
systemctl --user disable --now nemo-window-pruner.service
```

Do not enable both the Cinnamon autostart entry and the systemd user unit: two pruning daemons would duplicate observations and can issue competing close requests.

---

## 7. Known limitations and next-version candidates

| Limitation | Consequence | Potential v0.2 response |
|---|---|---|
| X11-only | Not reliable for Wayland sessions | Cinnamon/Muffin API extension or Wayland-specific research |
| Activity history starts at process launch | A previously important window appears initially “new” | Persistence of recent window paths/activity, with privacy review |
| No undo history | Closed directory must be reopened manually | Record directory URI/title before close; offer reopen command |
| Window title is not a stable directory identifier | Logs communicate behavior but cannot robustly restore context | Query Nemo/D-Bus capability or Cinnamon integration |
| Policy has no GUI | Configuration requires TOML editing | Cinnamon settings UI after policy validation |

### Exit criteria for promoting to v0.2

Promote beyond the PoC only after the dry-run/live trial answers these questions:

1. Does LRU cleanup trigger only on windows you would have closed manually?
2. Is current-workspace scoping correct, or do you want all-workspace cleanup?
3. Is automatic closing acceptable, or is a manual hotkey preferable?
4. Would URI-aware reopen history materially reduce risk?

---

## 8. Implementation evidence and source validation

| Key implementation decision | Validation source | Implication for v0.1 |
|---|---|---|
| Nemo is the Cinnamon file manager and offers `--tabs`, `--existing-window`, and `--quit` CLI options | Ubuntu Nemo manpage, package `nemo` 6.0.2 | Nemo can broadly reuse/quit windows, but selective per-window pruning is not a Nemo CLI feature |
| `_NET_ACTIVE_WINDOW` is the standardized property for the currently active window | freedesktop.org EWMH specification §3.8 | `xprop -root _NET_ACTIVE_WINDOW` is a standards-grounded focus signal on X11 |
| File-manager desktop windows may be a distinct EWMH desktop-type window | freedesktop.org EWMH implementation notes §9.2 | Exact `WM_CLASS=nemo.Nemo` matching prevents intended interaction with desktop management windows |
| `wmctrl -l` enumerates managed windows, `-x` includes `WM_CLASS`, and `-c` closes a selected window gracefully | Ubuntu `wmctrl(1)` manpage | A lightweight script can selectively request closure without killing the Nemo process |
| Nemo’s official extension repository contains content/integration extensions, not window lifecycle policy machinery | Linux Mint `nemo-extensions` repository | A PoC at the window-manager layer is proportionate before building a Cinnamon extension |

### Referenced sources

1. Ubuntu Manpages, **nemo — the Cinnamon File Manager**, Nemo 6.0.2-1ubuntu2: <https://manpages.ubuntu.com/manpages/noble/man1/nemo.1.html>
2. freedesktop.org, **Extended Window Manager Hints (EWMH), Version 1.5**, especially `_NET_ACTIVE_WINDOW` and implementation notes: <https://specifications.freedesktop.org/wm/latest-single/>
3. Ubuntu Manpages, **wmctrl — interact with an EWMH/NetWM compatible X Window Manager**: <https://manpages.ubuntu.com/manpages/focal/man1/wmctrl.1.html>
4. Linux Mint, **nemo-extensions** repository: <https://github.com/linuxmint/nemo-extensions>

---

## 9. Decision record

### Chosen approach: standalone X11 observer/controller + safe configuration

This is the smallest implementation that can validate the actual behavioral policy: whether closing least-recently-used excess Nemo windows improves daily navigation without losing valuable directory context.

### Alternatives deferred

| Alternative | Deferred because |
|---|---|
| Nemo action only | Requires manual invocation and cannot implement inactive-window policy cleanly |
| `nemo --quit` cleanup | Closes Nemo broadly rather than selectively |
| Cinnamon extension | Better long-term UX, but prematurely expensive before policy validation |
| Wayland-oriented implementation | Not required for the current Mint/Cinnamon X11 validation path and needs different APIs |
