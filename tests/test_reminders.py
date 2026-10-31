import xml.etree.ElementTree as ET
from datetime import datetime
from unittest import mock

from assistant.tools.reminders import NullScheduler, Reminders, Store, TaskScheduler

NOW = datetime(2026, 10, 31, 19, 50)


def make(tmp_path, scheduler=None, now=NOW):
    notes = []
    r = Reminders(Store(tmp_path / "r.db"), scheduler or NullScheduler(),
                  lambda t, b: notes.append((t, b)), now=lambda: now)
    return r, notes


def test_set_list_cancel(tmp_path):
    r, _ = make(tmp_path)
    a = r.set_reminder("call mom", "tomorrow at six")
    assert a["ok"] and a["due_iso"] == "2026-11-01T18:00" and a["due"] == "Sun 01 Nov 6:00 PM"
    b = r.set_reminder("check oven", "in 20 minutes")
    assert [x["text"] for x in r.list_reminders()["reminders"]] == ["check oven", "call mom"]
    assert r.cancel_reminder(a["id"])["ok"]
    assert [x["id"] for x in r.list_reminders()["reminders"]] == [b["id"]]
    assert r.store.get(a["id"])["status"] == "cancelled"  # kept, not deleted


def test_trimmed_when_is_expanded_from_transcript(tmp_path):
    r, _ = make(tmp_path)
    res = r.set_reminder("drink water", "4", transcript="remind me to drink water at 4")
    assert res["ok"] and res["due_iso"] == "2026-11-01T16:00"


def test_unresolvable_time_refused_and_nothing_stored(tmp_path):
    r, _ = make(tmp_path)
    assert r.set_reminder("x", "whenever")["ok"] is False
    assert r.set_reminder("x", "yesterday at 3")["ok"] is False
    assert r.list_reminders()["reminders"] == []


def test_cancel_unknown(tmp_path):
    r, _ = make(tmp_path)
    assert r.cancel_reminder(99)["ok"] is False
    assert r.cancel_reminder("abc")["ok"] is False


def test_fire_is_idempotent_and_fire_due(tmp_path):
    r, notes = make(tmp_path)
    rid = r.set_reminder("stretch", "in 20 minutes")["id"]
    assert r.fire_due() == 0
    later, notes2 = make(tmp_path, now=datetime(2026, 10, 31, 20, 30))
    assert later.fire_due() == 1 and notes2 == [("Reminder", "stretch")]
    assert later.fire(rid) is False and later.fire_due() == 0


def test_task_scheduler_xml_and_no_shell(tmp_path):
    run = mock.Mock()
    ts = TaskScheduler(r"C:\Py\pythonw.exe", r"C:\app\run.py", r"C:\app", run=run)
    captured = {}

    def fake_run(args, **kw):
        captured["args"], captured["kw"] = args, kw
        captured["xml"] = open(args[args.index("/XML") + 1], encoding="utf-16").read()
    run.side_effect = fake_run
    r, _ = make(tmp_path, ts)
    res = r.set_reminder("buy milk & <eggs>", "tomorrow at six")
    assert res["ok"]
    assert captured["args"][:4] == ["schtasks", "/Create", "/TN", f"WhistleAssistant\\Reminder-{res['id']}"]
    assert captured["kw"]["shell"] is False
    root = ET.fromstring(captured["xml"].encode("utf-16"))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:StartBoundary", ns).text == "2026-11-01T18:00:00"
    assert root.find(".//t:StartWhenAvailable", ns).text == "true"
    args = root.find(".//t:Arguments", ns).text
    assert args.endswith(f"--fire-reminder {res['id']}") and "milk" not in captured["xml"]
    r.cancel_reminder(res["id"])
    assert captured["args"][:2] == ["schtasks", "/Delete"]


def test_scheduler_failure_marks_failed(tmp_path):
    bad = mock.Mock(name="sched")
    bad.name = "task-scheduler"
    bad.schedule.side_effect = OSError("access denied")
    r, _ = make(tmp_path, bad)
    res = r.set_reminder("x", "in 5 minutes")
    assert res["ok"] is False and r.list_reminders()["reminders"] == []
