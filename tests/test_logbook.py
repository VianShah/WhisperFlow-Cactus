import json

from assistant.logbook import Logbook


def test_appends_jsonl_in_finetune_shape(tmp_path):
    lb = Logbook(tmp_path / "log.jsonl")
    lb.write({"mode": "command", "query": "open notepad",
              "answers": [{"name": "open_app", "arguments": {"name": "notepad"}}], "tools": []})
    lb.write({"mode": "command", "query": "x", "answers": [], "tools": []})
    rows = [json.loads(l) for l in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and {"ts", "query", "answers", "tools"} <= rows[0].keys()


def test_dictation_not_logged_by_default(tmp_path):
    lb = Logbook(tmp_path / "log.jsonl")
    lb.write({"mode": "dictate", "query": "my private email"})
    assert not (tmp_path / "log.jsonl").exists()
