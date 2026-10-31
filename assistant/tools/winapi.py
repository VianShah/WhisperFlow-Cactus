"""Thin Windows API layer (ctypes + pycaw). Everything OS-specific lives here so
executors can be tested with a fake. Not exercised in CI: verify on Windows."""
from __future__ import annotations

import ctypes
import os
import sys

WM_CLOSE = 0x0010
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
HWND_BROADCAST = 0xFFFF
SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


class NotWindows(RuntimeError):
    pass


class WinAPI:
    def __init__(self):
        if sys.platform != "win32":
            raise NotWindows("this action is only available on Windows")
        from ctypes import wintypes
        self.wt = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def _exe_of(self, hwnd) -> str:
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = self.wt.DWORD(len(buf))
            if self.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            self.kernel32.CloseHandle(h)

    def windows_for(self, exe_name: str) -> list[int]:
        """Visible, titled top-level windows of a process, front-most first."""
        exe_name = exe_name.lower()
        found = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, self.wt.HWND, self.wt.LPARAM)

        def cb(hwnd, _):
            if (self.user32.IsWindowVisible(hwnd)
                    and self.user32.GetWindowTextLengthW(hwnd) > 0
                    and not self.user32.GetWindow(hwnd, 4)  # GW_OWNER: skip owned popups
                    and self._exe_of(hwnd) == exe_name):
                found.append(hwnd)
            return True
        self.user32.EnumWindows(proto(cb), 0)
        return found

    def close_window(self, hwnd) -> None:
        # WM_CLOSE = the same as clicking X: the app may still ask to save.
        self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def focus_window(self, hwnd) -> None:
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, SW_RESTORE)
        # Windows only lets the foreground process change focus; a synthetic Alt
        # tap is the documented-in-practice way to satisfy that from a hotkey app.
        self.user32.keybd_event(VK_MENU, 0, 0, 0)
        self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        self.user32.SetForegroundWindow(hwnd)

    def set_volume(self, level: int) -> None:
        from pycaw.pycaw import AudioUtilities
        speakers = AudioUtilities.GetSpeakers()
        try:
            endpoint = speakers.EndpointVolume  # pycaw >= 20240210
        except AttributeError:
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import IAudioEndpointVolume
            iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            endpoint = ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))
        endpoint.SetMute(1 if level == 0 else 0, None)
        endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)

    def lock_screen(self) -> None:
        if not self.user32.LockWorkStation():
            raise OSError(ctypes.get_last_error(), "LockWorkStation failed")

    def sleep_display(self) -> None:
        self.user32.PostMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)


def default_api():
    try:
        return WinAPI()
    except NotWindows:
        return None
