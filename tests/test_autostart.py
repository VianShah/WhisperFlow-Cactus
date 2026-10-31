from unittest import mock

from assistant.autostart import NAME, Autostart


def test_enable_creates_shortcut_and_disable_removes_it(tmp_path):
    created = {}

    class FakeLink:
        def save(self):
            (tmp_path / NAME).write_text("lnk")
            created.update(vars(self))

    shell = mock.Mock()
    shell.CreateShortCut.return_value = FakeLink()
    a = Autostart(r"C:\app\run.py", r"C:\app", folder=tmp_path,
                  shell_factory=lambda: shell, python_exe=r"C:\Py\pythonw.exe")
    assert not a.is_enabled()
    a.enable()
    assert a.is_enabled()
    assert created["TargetPath"] == r"C:\Py\pythonw.exe"
    assert created["Arguments"] == r'"C:\app\run.py"' and created["WorkingDirectory"] == r"C:\app"
    assert a.disable() and not a.is_enabled()
    assert a.disable() is False
