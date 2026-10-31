"""Executors with every OS call mocked: nothing is actually launched."""
from unittest import mock

from assistant.tools.apps import AppLauncher
from assistant.tools.clock import get_time

ALLOW = {"notepad": "notepad.exe", "vscode": "code"}


def test_allowlisted_app_launches_without_shell():
    popen = mock.Mock()
    la = AppLauncher(ALLOW, popen=popen, which=lambda exe: f"C:/bin/{exe}")
    assert la.open_app("Notepad") == {"ok": True, "opened": "notepad"}
    popen.assert_called_once_with(["C:/bin/notepad.exe"], shell=False, close_fds=True)


def test_unknown_app_refused_and_nothing_runs():
    popen, start = mock.Mock(), mock.Mock()
    la = AppLauncher(ALLOW, popen=popen, which=lambda e: "/x", startfile=start)
    for evil in ["photoshop", "notepad & del C:\\*", "cmd.exe /c calc", "../../evil"]:
        assert la.open_app(evil)["ok"] is False
    popen.assert_not_called()
    start.assert_not_called()


def test_missing_executable_reports_error(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    la = AppLauncher(ALLOW, popen=mock.Mock(), which=lambda e: None)
    assert la.open_app("vscode")["ok"] is False


def test_windows_falls_back_to_startfile_with_config_string(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    start = mock.Mock()
    la = AppLauncher({"chrome": "chrome.exe"}, popen=mock.Mock(), which=lambda e: None,
                     startfile=start)
    assert la.open_app("chrome")["ok"]
    start.assert_called_once_with("chrome.exe")


def test_get_time_format():
    from datetime import datetime
    r = get_time(datetime(2026, 10, 31, 9, 5))
    assert r["time"] == "9:05 AM" and r["date"] == "Saturday 31 October"


def test_no_shell_anywhere_in_source():
    """Spec 8.2, checked on the syntax tree (comments/docstrings don't count)."""
    import ast
    from pathlib import Path
    bad = []
    for path in Path("assistant").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            full = ast.unparse(f)
            if name in ("eval", "exec") or full in ("os.system", "os.popen"):
                bad.append(f"{path}:{node.lineno} {full}")
            for kw in node.keywords:
                if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                    bad.append(f"{path}:{node.lineno} shell={ast.unparse(kw.value)}")
    assert bad == []


# ---- Phase 3: windows + system control, with a fake Windows API ----
from assistant.tools.apps import SystemControl


class FakeAPI:
    def __init__(self, windows=None):
        self.windows = windows or {}
        self.calls = []

    def windows_for(self, exe):
        self.calls.append(("windows_for", exe))
        return self.windows.get(exe, [])

    def close_window(self, h): self.calls.append(("close", h))
    def focus_window(self, h): self.calls.append(("focus", h))
    def set_volume(self, v): self.calls.append(("volume", v))
    def lock_screen(self): self.calls.append(("lock",))
    def sleep_display(self): self.calls.append(("sleep",))


def test_close_window_matches_process_and_closes_frontmost_only():
    api = FakeAPI({"notepad.exe": [101, 102]})
    la = AppLauncher(ALLOW, api=api)
    assert la.close_window("notepad") == {"ok": True, "closed": "notepad"}
    assert ("close", 101) in api.calls and ("close", 102) not in api.calls


def test_vscode_process_name_derived_from_allowlist():
    api = FakeAPI({"code.exe": [7]})
    assert AppLauncher(ALLOW, api=api).focus_window("vscode")["ok"]
    assert ("focus", 7) in api.calls


def test_process_name_override():
    api = FakeAPI({"spotify.exe": [9]})
    la = AppLauncher({"music": "C:/x/launcher.exe"}, api=api, process_names={"music": "Spotify.exe"})
    assert la.focus_window("music")["ok"]


def test_window_actions_refuse_unknown_and_missing():
    api = FakeAPI({})
    la = AppLauncher(ALLOW, api=api)
    assert la.close_window("explorer")["ok"] is False
    assert "no open window" in la.focus_window("notepad")["error"]
    assert not any(c[0] in ("close", "focus") for c in api.calls)


def test_volume_validated_and_coerced():
    api = FakeAPI()
    sc = SystemControl(api)
    assert sc.set_volume("30") == {"ok": True, "volume": 30}  # Needle sometimes sends a string
    assert sc.set_volume(150)["ok"] is False
    assert sc.set_volume(-1)["ok"] is False
    assert sc.set_volume("loud")["ok"] is False
    assert sc.set_volume("mute") == {"ok": True, "volume": 0}  # observed model output
    assert sc.set_volume("80%") == {"ok": True, "volume": 80}
    assert api.calls == [("volume", 30), ("volume", 0), ("volume", 80)]


def test_lock_and_sleep():
    api = FakeAPI()
    sc = SystemControl(api)
    assert sc.lock_screen()["ok"] and sc.sleep_display()["ok"]
    assert api.calls == [("lock",), ("sleep",)]


def test_non_windows_reports_cleanly():
    sc = SystemControl(api=False)
    assert "only available on Windows" in sc.lock_screen()["error"]
    la = AppLauncher(ALLOW, api=False)
    assert "only available on Windows" in la.close_window("notepad")["error"]
