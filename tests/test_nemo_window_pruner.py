from __future__ import annotations

import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).parents[1] / "src" / "nemo_window_pruner.py"
spec = importlib.util.spec_from_file_location("nemo_window_pruner", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class ParsingTests(unittest.TestCase):
    def test_parse_windows_and_exact_nemo_matching(self) -> None:
        output = (
            "0x04e0000b  0 nemo.Nemo workstation Home - File Manager\n"
            "0x04e0000c  1 nemo-desktop.Nemo-desktop workstation Desktop\n"
            "0x05e0000d  0 ghostty.com.mitchellh.ghostty workstation terminal\n"
        )
        windows = mod.parse_windows(output)
        cfg = mod.Config()
        self.assertEqual(windows[0].window_id, "0x04e0000b")
        self.assertTrue(mod.is_target_window(windows[0], cfg))
        self.assertFalse(mod.is_target_window(windows[1], cfg))

    def test_parse_active_window_normalizes_identifier(self) -> None:
        self.assertEqual(
            mod.parse_active_window("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x4e0000b\n"),
            "0x04e0000b",
        )

    def test_parse_current_desktop(self) -> None:
        output = "0  - DG: 1920x1080 VP: 0,0 WA: 0,0 1920x1040 One\n1  * DG: 1920x1080 VP: 0,0 WA: 0,0 1920x1040 Two\n"
        self.assertEqual(mod.parse_current_desktop(output), 1)


class PolicyTests(unittest.TestCase):
    def make_windows(self, count: int) -> list[mod.ManagedWindow]:
        return [
            mod.ManagedWindow(f"0x{i:08x}", 0, "nemo.Nemo", "host", f"Window {i}")
            for i in range(1, count + 1)
        ]

    def test_does_not_close_at_or_below_limit(self) -> None:
        cfg = mod.Config(max_windows=3, min_inactive_minutes=0, startup_grace_minutes=0)
        pruner = mod.WindowPruner(cfg)
        windows = self.make_windows(3)
        pruner.observe(windows, windows[-1].window_id, now=100.0)
        self.assertEqual(pruner.eligible_closures(windows, windows[-1].window_id, now=200.0), [])

    def test_closes_lru_but_never_active_window(self) -> None:
        cfg = mod.Config(max_windows=2, min_inactive_minutes=0, startup_grace_minutes=0, max_closes_per_cycle=1)
        pruner = mod.WindowPruner(cfg)
        windows = self.make_windows(3)
        pruner.observe(windows, windows[0].window_id, now=100.0)
        pruner.observe(windows, windows[1].window_id, now=110.0)
        pruner.observe(windows, windows[2].window_id, now=120.0)
        closures = pruner.eligible_closures(windows, windows[2].window_id, now=130.0)
        self.assertEqual([window.window_id for window in closures], [windows[0].window_id])
        self.assertNotIn(windows[2], closures)

    def test_startup_grace_protects_unknown_history(self) -> None:
        cfg = mod.Config(max_windows=1, min_inactive_minutes=0, startup_grace_minutes=10)
        pruner = mod.WindowPruner(cfg)
        windows = self.make_windows(2)
        pruner.observe(windows, windows[-1].window_id, now=100.0)
        self.assertEqual(pruner.eligible_closures(windows, windows[-1].window_id, now=699.0), [])
        self.assertEqual(len(pruner.eligible_closures(windows, windows[-1].window_id, now=701.0)), 1)


if __name__ == "__main__":
    unittest.main()
