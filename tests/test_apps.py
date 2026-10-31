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
