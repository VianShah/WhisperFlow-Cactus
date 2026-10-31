import os
import time
from unittest import mock

from assistant.tools.files import FileSearch, sanitize_query


def tree(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Budget 2026.xlsx").write_text("x")
    time.sleep(0.01)
    (tmp_path / "docs" / "budget-old.xlsx").write_text("x")
    (tmp_path / "setup_budget.exe").write_text("x")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "budget secret.txt").write_text("x")
    return tmp_path


def fs(tmp_path, **kw):
    return FileSearch(everything_cli=None, roots=[str(tmp_path)],
                      opener=kw.pop("opener", mock.Mock()), revealer=kw.pop("revealer", mock.Mock()), **kw)


def test_sanitize_blocks_switches():
    assert sanitize_query("-export-csv C:/x.csv budget") == "export-csv Cx.csv budget"
    assert sanitize_query("/a-d //cmd") == "a-d cmd"
    assert sanitize_query("---") == ""


def test_walk_finds_newest_first_and_skips_hidden(tmp_path):
    f = fs(tree(tmp_path))
    r = f.find_file("budget")
    names = [os.path.basename(p) for p in r["results"]]
    assert set(names) == {"Budget 2026.xlsx", "budget-old.xlsx", "setup_budget.exe"}
    assert "budget secret.txt" not in names
    assert r["backend"] == "walk" and "Everything" in r["note"]


def test_open_by_number_only_from_last_results(tmp_path):
    opener = mock.Mock()
    f = fs(tree(tmp_path), opener=opener)
    assert f.open_file(1)["ok"] is False  # no search yet
    f.find_file("budget 2026")
    assert f.open_file(1)["ok"] and opener.call_args[0][0].endswith("Budget 2026.xlsx")
    assert f.open_file(5)["ok"] is False and f.open_file("two")["ok"] is False


def test_executables_revealed_not_opened(tmp_path):
    opener, revealer = mock.Mock(), mock.Mock()
    f = fs(tree(tmp_path), opener=opener, revealer=revealer)
    f.find_file("setup")
    r = f.open_file(1)
    assert r["ok"] and "revealed" in r
    opener.assert_not_called()
    revealer.assert_called_once()


def test_everything_backend_argv(tmp_path):
    run = mock.Mock(return_value=mock.Mock(stdout="C:\\a\\budget.xlsx\nC:\\b\\budget.pdf\n"))
    f = FileSearch(everything_cli="es.exe", which=lambda e: "C:/tools/es.exe", run=run)
    r = f.find_file("-export-csv budget", limit=50)
    args, kw = run.call_args
    assert args[0] == ["C:/tools/es.exe", "-n", "10", "/a-d", "export-csv budget"]
    assert kw["shell"] is False and r["results"] == ["C:\\a\\budget.xlsx", "C:\\b\\budget.pdf"]


def test_missing_roots_and_empty_query(tmp_path):
    f = FileSearch(everything_cli=None, roots=[str(tmp_path / "nope")])
    assert f.find_file("x")["results"] == []
    assert f.find_file("--")["ok"] is False
