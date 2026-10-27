from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))
from benchmark_common import clean_runtime_environment, require_file


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("MGA2_OUTLINE_UI_TEST_EXE"),
    "set MGA2_OUTLINE_UI_TEST_EXE on an interactive Windows desktop",
)
class OutlineLauncherIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.executable = require_file(
            Path(os.environ["MGA2_OUTLINE_UI_TEST_EXE"]), "executable"
        )
        cls.user = ctypes.WinDLL("user32", use_last_error=True)
        cls.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        cls.enum_callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        cls.user.EnumWindows.argtypes = [cls.enum_callback, wintypes.LPARAM]
        cls.user.EnumChildWindows.argtypes = [
            wintypes.HWND, cls.enum_callback, wintypes.LPARAM
        ]
        cls.user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
        ]
        cls.user.GetParent.argtypes = [wintypes.HWND]
        cls.user.GetParent.restype = wintypes.HWND
        cls.user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        cls.user.GetDlgItem.restype = wintypes.HWND
        cls.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        cls.user.GetWindowTextW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
        ]
        cls.user.GetClassNameW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int
        ]
        cls.user.GetWindowRect.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.RECT)
        ]
        cls.user.GetClientRect.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.RECT)
        ]
        cls.user.MapWindowPoints.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.POINTER(wintypes.POINT),
            wintypes.UINT,
        ]
        cls.user.IsWindowVisible.argtypes = [wintypes.HWND]
        cls.user.IsWindow.argtypes = [wintypes.HWND]
        cls.user.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        cls.user.SendMessageW.restype = ctypes.c_ssize_t
        cls.user.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        cls.user.GetDC.argtypes = [wintypes.HWND]
        cls.user.GetDC.restype = wintypes.HDC
        cls.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        cls.user.DrawTextW.argtypes = [
            wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
            ctypes.POINTER(wintypes.RECT), wintypes.UINT,
        ]
        cls.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        cls.gdi.SelectObject.restype = wintypes.HANDLE

    def text(self, window: int) -> str:
        length = self.user.GetWindowTextLengthW(window)
        buffer = ctypes.create_unicode_buffer(length + 1)
        self.user.GetWindowTextW(window, buffer, len(buffer))
        return buffer.value

    def windows(self, process: subprocess.Popen[bytes]) -> list[int]:
        windows: list[int] = []

        @self.enum_callback
        def collect(window: int, unused: int) -> bool:
            owner = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == process.pid and self.user.IsWindowVisible(window):
                windows.append(window)
            return True

        self.user.EnumWindows(collect, 0)
        return windows

    def wait_window(self, process: subprocess.Popen[bytes], title: str) -> int:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail(f"launcher exited before opening {title!r}")
            for window in self.windows(process):
                if self.text(window) == title:
                    return window
            time.sleep(0.05)
        self.fail(f"launcher did not open {title!r}")

    def combo(self, dialog: int, identifier: int) -> tuple[int, list[str], int]:
        control = self.user.GetDlgItem(dialog, identifier)
        self.assertTrue(control, f"missing combo {identifier}")
        count = self.user.SendMessageW(control, 0x146, 0, 0)
        labels = []
        for index in range(count):
            length = self.user.SendMessageW(control, 0x149, index, 0)
            self.assertGreaterEqual(length, 0)
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user.SendMessageW(
                control, 0x148, index, ctypes.addressof(buffer)
            )
            labels.append(buffer.value)
        return control, labels, self.user.SendMessageW(control, 0x147, 0, 0)

    def select(self, dialog: int, identifier: int, label: str) -> None:
        control, labels, _ = self.combo(dialog, identifier)
        self.assertIn(label, labels)
        self.assertNotEqual(
            self.user.SendMessageW(control, 0x14E, labels.index(label), 0), -1
        )

    def assert_layout(self, dialog: int) -> None:
        client = wintypes.RECT()
        self.assertTrue(self.user.GetClientRect(dialog, ctypes.byref(client)))
        children: list[int] = []

        @self.enum_callback
        def collect(window: int, unused: int) -> bool:
            if self.user.GetParent(window) == dialog and self.user.IsWindowVisible(window):
                children.append(window)
            return True

        self.user.EnumChildWindows(dialog, collect, 0)
        rectangles: list[tuple[str, wintypes.RECT]] = []
        for child in children:
            rect = wintypes.RECT()
            self.assertTrue(self.user.GetWindowRect(child, ctypes.byref(rect)))
            self.user.MapWindowPoints(
                None, dialog, ctypes.cast(ctypes.byref(rect), ctypes.POINTER(wintypes.POINT)), 2
            )
            label = self.text(child)
            self.assertGreaterEqual(rect.left, 0, label)
            self.assertGreaterEqual(rect.top, 0, label)
            self.assertLessEqual(rect.right, client.right, label)
            self.assertLessEqual(rect.bottom, client.bottom, label)
            for other_label, other in rectangles:
                overlap = (
                    rect.left < other.right and other.left < rect.right
                    and rect.top < other.bottom and other.top < rect.bottom
                )
                self.assertFalse(overlap, f"overlap: {label!r}, {other_label!r}")
            rectangles.append((label, rect))
            class_name = ctypes.create_unicode_buffer(64)
            self.user.GetClassNameW(child, class_name, len(class_name))
            if class_name.value == "Static" and label:
                dc = self.user.GetDC(child)
                self.assertTrue(dc)
                font = self.user.SendMessageW(child, 0x31, 0, 0)
                previous = self.gdi.SelectObject(dc, font)
                measured = wintypes.RECT(0, 0, rect.right - rect.left, 0)
                self.user.DrawTextW(dc, label, -1, ctypes.byref(measured), 0x400 | 0x10)
                self.gdi.SelectObject(dc, previous)
                self.user.ReleaseDC(child, dc)
                self.assertLessEqual(
                    measured.bottom, rect.bottom - rect.top,
                    f"clipped label: {label!r}",
                )

    def reject_sharper(self, process: subprocess.Popen[bytes], dialog: int) -> None:
        self.user.PostMessageW(dialog, 0x111, 1, 0)
        error = self.wait_window(process, "Graphics Settings")
        messages: list[str] = []

        @self.enum_callback
        def collect_error(window: int, unused: int) -> bool:
            messages.append(self.text(window))
            return True

        self.user.EnumChildWindows(error, collect_error, 0)
        self.assertIn(
            "Sharper outlines require the D3D12 or Vulkan renderer.", messages
        )
        self.user.PostMessageW(error, 0x10, 0, 0)
        deadline = time.monotonic() + 5
        while self.user.IsWindow(error) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(self.user.IsWindow(error), "error dialog stayed open")

    def start(
        self, output: Path, config: Path, executable: Path | None = None
    ) -> subprocess.Popen[bytes]:
        environment = clean_runtime_environment()
        environment.update({
            "SR_GRAPHICS_CONFIG": str(config),
            "SR_INPUT_CONFIG": "0",
            "SR_INPUT_HOT_RELOAD": "0",
        })
        return subprocess.Popen(
            [str(executable or self.executable), "--configure"],
            cwd=output, env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def close(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            for window in self.windows(process):
                self.user.PostMessageW(window, 0x10, 0, 0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)

    def test_persistence_layout_and_software_rejection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mga2-outline-ui-") as directory:
            output = Path(directory)
            config = output / "graphics.ini"
            config.write_text(
                "renderer=vk\ninternal_resolution=4\ntexture_scale=1\n"
                "d3d12_full_rate=1\nanti_aliasing=off\n"
                "skip_startup=on\noutlines=original\n",
                encoding="ascii",
            )
            for renderer, mode, token in (
                ("Vulkan", "Sharper (D3D12 / Vulkan)", "sharper"),
                ("D3D12 hardware", "Off", "off"),
                ("Software reference", "Off", "off"),
            ):
                with self.subTest(renderer=renderer):
                    process = self.start(output, config)
                    try:
                        dialog = self.wait_window(process, "Metal Gear Acid 2 Graphics")
                        self.assert_layout(dialog)
                        _, labels, _ = self.combo(dialog, 1007)
                        self.assertEqual(
                            labels, ["Original", "Sharper (D3D12 / Vulkan)", "Off"]
                        )
                        self.select(dialog, 1001, renderer)
                        if renderer == "Software reference":
                            self.select(dialog, 1007, "Sharper (D3D12 / Vulkan)")
                            self.reject_sharper(process, dialog)
                        self.select(dialog, 1007, mode)
                        self.user.PostMessageW(dialog, 0x111, 1, 0)
                        controller = self.wait_window(process, "Metal Gear Acid 2 Controller")
                        self.user.PostMessageW(controller, 0x10, 0, 0)
                        self.assertEqual(process.wait(timeout=10), 0)
                    finally:
                        self.close(process)
                    self.assertIn(f"outlines = {token}", config.read_text(encoding="ascii"))
                    process = self.start(output, config)
                    try:
                        dialog = self.wait_window(process, "Metal Gear Acid 2 Graphics")
                        _, labels, selected = self.combo(dialog, 1001)
                        self.assertEqual(labels[selected], renderer)
                        _, labels, selected = self.combo(dialog, 1007)
                        self.assertEqual(labels[selected], mode)
                    finally:
                        self.close(process)

    @unittest.skipUnless(
        os.environ.get("MGA2_OUTLINE_SOFTWARE_UI_TEST_EXE"),
        "set MGA2_OUTLINE_SOFTWARE_UI_TEST_EXE to test the software-only dialog",
    )
    def test_software_only_automatic_rejects_sharper(self) -> None:
        executable = require_file(
            Path(os.environ["MGA2_OUTLINE_SOFTWARE_UI_TEST_EXE"]),
            "software-only dialog host",
        )
        with tempfile.TemporaryDirectory(prefix="mga2-outline-ui-sw-") as directory:
            output = Path(directory)
            config = output / "graphics.ini"
            original = (
                "renderer=auto\ninternal_resolution=1\ntexture_scale=1\n"
                "anti_aliasing=off\noutlines=original\n"
            )
            config.write_text(original, encoding="ascii")
            process = self.start(output, config, executable)
            try:
                dialog = self.wait_window(process, "Metal Gear Acid 2 Graphics")
                _, renderers, _ = self.combo(dialog, 1001)
                self.assertEqual(renderers, ["Automatic", "Software reference"])
                self.select(dialog, 1007, "Sharper (D3D12 / Vulkan)")
                self.reject_sharper(process, dialog)
                self.assertEqual(config.read_text(encoding="ascii"), original)
                self.select(dialog, 1007, "Off")
                self.user.PostMessageW(dialog, 0x111, 1, 0)
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertIn("outlines = off", config.read_text(encoding="ascii"))
            finally:
                self.close(process)


if __name__ == "__main__":
    unittest.main()
