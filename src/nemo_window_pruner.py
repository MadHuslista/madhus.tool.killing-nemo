#!/usr/bin/env python3
"""Nemo Window Pruner PoC v0.1.

Safely prunes excess inactive Nemo file-manager windows on X11 desktops by
observing EWMH window metadata via wmctrl/xprop and sending a graceful close
request to the least-recently-focused eligible window.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Iterable, Sequence

APP_NAME = "nemo-window-pruner"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / APP_NAME / "config.toml"
LOG = logging.getLogger(APP_NAME)


class PrunerError(RuntimeError):
    """Expected environment or command failure."""


@dataclasses.dataclass(frozen=True)
class ManagedWindow:
    window_id: str
    desktop: int
    wm_class: str
    host: str
    title: str


@dataclasses.dataclass
class WindowActivity:
    first_seen: float
    last_focused: float


@dataclasses.dataclass
class Config:
    max_windows: int = 5
    min_inactive_minutes: float = 30.0
    startup_grace_minutes: float = 30.0
    poll_interval_seconds: float = 2.0
    max_closes_per_cycle: int = 1
    protect_focused_window: bool = True
    scope: str = "current_workspace"
    dry_run: bool = True
    wm_class_instance: str = "nemo"
    wm_class_name: str = "Nemo"
    log_level: str = "INFO"

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            raise PrunerError(f"Configuration file not found: {path}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise PrunerError(f"Unable to read TOML configuration {path}: {exc}") from exc
        policy = raw.get("policy", {})
        matching = raw.get("matching", {})
        logging_cfg = raw.get("logging", {})
        cfg = cls(
            max_windows=int(policy.get("max_windows", cls.max_windows)),
            min_inactive_minutes=float(policy.get("min_inactive_minutes", cls.min_inactive_minutes)),
            startup_grace_minutes=float(policy.get("startup_grace_minutes", cls.startup_grace_minutes)),
            poll_interval_seconds=float(policy.get("poll_interval_seconds", cls.poll_interval_seconds)),
            max_closes_per_cycle=int(policy.get("max_closes_per_cycle", cls.max_closes_per_cycle)),
            protect_focused_window=bool(policy.get("protect_focused_window", cls.protect_focused_window)),
            scope=str(policy.get("scope", cls.scope)),
            dry_run=bool(policy.get("dry_run", cls.dry_run)),
            wm_class_instance=str(matching.get("wm_class_instance", cls.wm_class_instance)),
            wm_class_name=str(matching.get("wm_class_name", cls.wm_class_name)),
            log_level=str(logging_cfg.get("level", cls.log_level)).upper(),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.max_windows < 1:
            raise PrunerError("policy.max_windows must be >= 1")
        if self.min_inactive_minutes < 0 or self.startup_grace_minutes < 0:
            raise PrunerError("inactivity and grace durations must be >= 0")
        if self.poll_interval_seconds <= 0:
            raise PrunerError("policy.poll_interval_seconds must be > 0")
        if self.max_closes_per_cycle < 1:
            raise PrunerError("policy.max_closes_per_cycle must be >= 1")
        if self.scope not in {"current_workspace", "all_workspaces"}:
            raise PrunerError("policy.scope must be current_workspace or all_workspaces")
        if not self.wm_class_instance or not self.wm_class_name:
            raise PrunerError("matching WM_CLASS values must not be empty")


def run_command(command: Sequence[str]) -> str:
    """Execute a local inspection/control command with bounded runtime."""
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError as exc:
        raise PrunerError(f"Required command not found: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PrunerError(f"Command timed out: {' '.join(command)}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise PrunerError(f"Command failed ({' '.join(command)}): {detail}")
    return result.stdout


def normalize_window_id(raw: str) -> str:
    return f"0x{int(raw.strip(), 16):08x}"


def parse_windows(output: str) -> list[ManagedWindow]:
    """Parse `wmctrl -lx` output: id, desktop, WM_CLASS, host, title."""
    windows: list[ManagedWindow] = []
    for line in output.splitlines():
        parts = line.split(maxsplit=4)
        if len(parts) < 4:
            continue
        try:
            window_id = normalize_window_id(parts[0])
            desktop = int(parts[1])
        except ValueError:
            continue
        windows.append(
            ManagedWindow(
                window_id=window_id,
                desktop=desktop,
                wm_class=parts[2],
                host=parts[3],
                title=parts[4] if len(parts) == 5 else "",
            )
        )
    return windows


def parse_active_window(output: str) -> str | None:
    # Typical output: _NET_ACTIVE_WINDOW(WINDOW): window id # 0x04e0000b
    marker = "#"
    if marker not in output:
        return None
    raw_id = output.rsplit(marker, maxsplit=1)[1].strip().split()[0]
    if raw_id in {"0x0", "0x00000000", "None"}:
        return None
    try:
        return normalize_window_id(raw_id)
    except ValueError:
        return None


def parse_current_desktop(output: str) -> int:
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "*":
            return int(parts[0])
    raise PrunerError("Unable to determine current workspace from `wmctrl -d`")


def is_target_window(window: ManagedWindow, cfg: Config) -> bool:
    expected = f"{cfg.wm_class_instance}.{cfg.wm_class_name}".casefold()
    return window.wm_class.casefold() == expected


def scope_windows(windows: Iterable[ManagedWindow], cfg: Config, current_desktop: int) -> list[ManagedWindow]:
    targets = [window for window in windows if is_target_window(window, cfg)]
    if cfg.scope == "all_workspaces":
        return targets
    return [window for window in targets if window.desktop == current_desktop]


class WindowPruner:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.activity: dict[str, WindowActivity] = {}
        self._stopping = False

    def stop(self, *_args: object) -> None:
        self._stopping = True

    def observe(self, windows: list[ManagedWindow], active_window_id: str | None, now: float) -> None:
        present = {window.window_id for window in windows}
        for closed_id in set(self.activity) - present:
            del self.activity[closed_id]
        for window in windows:
            self.activity.setdefault(window.window_id, WindowActivity(first_seen=now, last_focused=now))
        if active_window_id in self.activity:
            self.activity[active_window_id].last_focused = now

    def eligible_closures(
        self,
        windows: list[ManagedWindow],
        active_window_id: str | None,
        now: float,
    ) -> list[ManagedWindow]:
        excess = len(windows) - self.cfg.max_windows
        if excess <= 0:
            return []
        min_inactive_seconds = self.cfg.min_inactive_minutes * 60.0
        grace_seconds = self.cfg.startup_grace_minutes * 60.0
        candidates: list[ManagedWindow] = []
        for window in windows:
            state = self.activity[window.window_id]
            if self.cfg.protect_focused_window and window.window_id == active_window_id:
                continue
            if now - state.first_seen < grace_seconds:
                continue
            if now - state.last_focused < min_inactive_seconds:
                continue
            candidates.append(window)
        candidates.sort(
            key=lambda window: (
                self.activity[window.window_id].last_focused,
                self.activity[window.window_id].first_seen,
                window.window_id,
            )
        )
        close_count = min(excess, self.cfg.max_closes_per_cycle, len(candidates))
        return candidates[:close_count]

    def read_snapshot(self) -> tuple[list[ManagedWindow], str | None, int]:
        windows = parse_windows(run_command(["wmctrl", "-lx"]))
        active = parse_active_window(run_command(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
        current_desktop = parse_current_desktop(run_command(["wmctrl", "-d"]))
        return windows, active, current_desktop

    def cycle(self) -> None:
        all_windows, active_id, current_desktop = self.read_snapshot()
        targets = scope_windows(all_windows, self.cfg, current_desktop)
        now = time.monotonic()
        self.observe(targets, active_id, now)
        closures = self.eligible_closures(targets, active_id, now)
        for window in closures:
            state = self.activity[window.window_id]
            inactive_minutes = (now - state.last_focused) / 60.0
            action = "WOULD_CLOSE" if self.cfg.dry_run else "CLOSE"
            LOG.info(
                "%s id=%s desktop=%s inactive=%.1fmin title=%r",
                action,
                window.window_id,
                window.desktop,
                inactive_minutes,
                window.title,
            )
            if not self.cfg.dry_run:
                run_command(["wmctrl", "-i", "-c", window.window_id])
                self.activity.pop(window.window_id, None)

    def run(self, once: bool = False) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        mode = "DRY-RUN" if self.cfg.dry_run else "LIVE"
        LOG.info(
            "Started in %s mode: max_windows=%d inactive>=%.1fmin grace=%.1fmin scope=%s",
            mode,
            self.cfg.max_windows,
            self.cfg.min_inactive_minutes,
            self.cfg.startup_grace_minutes,
            self.cfg.scope,
        )
        while not self._stopping:
            try:
                self.cycle()
            except PrunerError as exc:
                LOG.error("Cycle failed: %s", exc)
                if once:
                    raise
            if once:
                return
            time.sleep(self.cfg.poll_interval_seconds)
        LOG.info("Stopped")


def validate_environment() -> None:
    if shutil.which("wmctrl") is None:
        raise PrunerError("Missing dependency `wmctrl`; install with: sudo apt install wmctrl")
    if shutil.which("xprop") is None:
        raise PrunerError("Missing dependency `xprop`; install with: sudo apt install x11-utils")
    session_type = os.environ.get("XDG_SESSION_TYPE", "").casefold()
    if session_type == "wayland":
        raise PrunerError("This v0.1 PoC supports X11 only; Wayland/XWayland cannot provide reliable full window control.")
    if not os.environ.get("DISPLAY"):
        raise PrunerError("DISPLAY is not set. Start the tool inside your Cinnamon graphical session.")
    run_command(["wmctrl", "-m"])


def print_discovery(cfg: Config) -> None:
    validate_environment()
    windows = parse_windows(run_command(["wmctrl", "-lx"]))
    current = parse_current_desktop(run_command(["wmctrl", "-d"]))
    active = parse_active_window(run_command(["xprop", "-root", "_NET_ACTIVE_WINDOW"]))
    matching = [window for window in windows if "nemo" in window.wm_class.casefold()]
    print(f"DISPLAY={os.environ.get('DISPLAY', '')} XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE', 'unknown')}")
    print(f"current_workspace={current} active_window={active or 'none'}")
    print(f"configured_WM_CLASS={cfg.wm_class_instance}.{cfg.wm_class_name}")
    if not matching:
        print("No managed windows with 'nemo' in WM_CLASS found. Open two Nemo windows and rerun.")
        return
    print("Detected Nemo-like managed windows:")
    for window in matching:
        matched = "MATCH" if is_target_window(window, cfg) else "NOT_MATCH"
        focus = " ACTIVE" if window.window_id == active else ""
        print(f"  {matched}{focus} id={window.window_id} desktop={window.desktop} WM_CLASS={window.wm_class} title={window.title!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely prune inactive excess Nemo windows on X11.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="TOML configuration path")
    parser.add_argument("--discover", action="store_true", help="Print Nemo window WM_CLASS data and exit")
    parser.add_argument("--once", action="store_true", help="Run one policy evaluation and exit")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Override configuration and allow graceful closing")
    mode.add_argument("--dry-run", action="store_true", help="Override configuration and never close windows")
    parser.add_argument("--max-windows", type=int, help="Override policy.max_windows")
    parser.add_argument("--min-inactive-minutes", type=float, help="Override policy.min_inactive_minutes")
    parser.add_argument("--startup-grace-minutes", type=float, help="Override policy.startup_grace_minutes")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = Config.load(args.config)
        if args.live:
            cfg.dry_run = False
        if args.dry_run:
            cfg.dry_run = True
        if args.max_windows is not None:
            cfg.max_windows = args.max_windows
        if args.min_inactive_minutes is not None:
            cfg.min_inactive_minutes = args.min_inactive_minutes
        if args.startup_grace_minutes is not None:
            cfg.startup_grace_minutes = args.startup_grace_minutes
        cfg.validate()
        logging.basicConfig(
            level=getattr(logging, cfg.log_level, logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        if args.discover:
            print_discovery(cfg)
            return 0
        validate_environment()
        WindowPruner(cfg).run(once=args.once)
        return 0
    except PrunerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
