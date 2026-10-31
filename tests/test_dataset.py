import json

from assistant import dataset, vocab

SCHEMAS = [{"name": "open_app", "parameters": {"type": "object", "properties": {
    "name": {"type": "string", "enum": ["notepad", "chrome"]}}, "required": ["name"]}},
    {"name": "set_volume", "parameters": {"type": "object", "properties": {
        "level": {"type": "integer"}}, "required": ["level"]}}]


def write_log(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


ROWS = [
    {"ts": "1", "mode": "command", "query": "Open Notepad",
     "answers": [{"name": "open_app", "arguments": {"name": "notepad"}}], "executed": True},
    {"ts": "2", "mode": "command", "query": "Switch to Chrome",
     "answers": [{"name": "open_app", "arguments": {"name": "chrome"}}], "executed": False},
    {"ts": "3", "mode": "command", "query": "purple monkey", "answers": [], "executed": False},
    {"ts": "4", "mode": "command", "query": "Set the volume to 50", "answers": [], "executed": False},
    {"ts": "5", "mode": "command", "query": "garbled", "answers": [], "executed": False},
]


def test_review_then_export(tmp_path):
    log, corr = tmp_path / "log.jsonl", tmp_path / "corr.jsonl"
    write_log(log, ROWS)
    # row1 ok, row2 skip, row3 ok(no tool), row4 fix -> set_volume(50), row5 drop
    answers = iter(["", "s", "", "f", "2", "50", "d"])
    n = dataset.review(log, corr, SCHEMAS, ask=lambda _: next(answers), say=lambda *_: None)
    assert n == 4
    info = dataset.export(log, corr, SCHEMAS, tmp_path / "ft", val=0, test=0)
    rows = [json.loads(l) for l in (tmp_path / "ft" / "train.jsonl").read_text().splitlines()]
    by_q = {r["query"]: r["answers"] for r in rows}
    assert by_q == {
        "Open Notepad": [{"name": "open_app", "arguments": {"name": "notepad"}}],
        "purple monkey": [],
        "Set the volume to 50": [{"name": "set_volume", "arguments": {"level": 50}}],
    }
    assert all(r["tools"] == SCHEMAS for r in rows)
    assert info["total"] == 3  # skipped and dropped rows are not exported


def test_review_resumes_and_log_untouched(tmp_path):
    log, corr = tmp_path / "log.jsonl", tmp_path / "corr.jsonl"
    write_log(log, ROWS)
    before = log.read_text()
    dataset.review(log, corr, SCHEMAS, ask=lambda _: "q", say=lambda *_: None)
    answers = iter(["", "q"])
    dataset.review(log, corr, SCHEMAS, ask=lambda _: next(answers), say=lambda *_: None)
    seen = []
    dataset.review(log, corr, SCHEMAS, ask=lambda _: "q", say=lambda m="": seen.append(m))
    assert seen[0].startswith("4 command(s)") and log.read_text() == before


def test_export_dedups_and_merges_seed(tmp_path):
    log, corr = tmp_path / "log.jsonl", tmp_path / "corr.jsonl"
    write_log(log, ROWS[:1])
    dataset.review(log, corr, SCHEMAS, ask=lambda _: "", say=lambda *_: None)
    seed = [{"query": "open notepad", "answers": [{"name": "open_app", "arguments": {"name": "notepad"}}]},
            {"query": "start chrome", "answers": [{"name": "open_app", "arguments": {"name": "chrome"}}]}]
    info = dataset.export(log, corr, SCHEMAS, tmp_path / "ft", val=0, test=0, extra=seed)
    assert info["total"] == 2 and info["sources"] == {"log": 1, "seed": 1}


def test_vocab_suggestions():
    rows = [{"mode": "command", "executed": True,
             "answers": [{"name": "set_reminder", "arguments": {"text": "call Maham about Kollect"}}]},
            {"mode": "command", "executed": True,
             "answers": [{"name": "set_reminder", "arguments": {"text": "email Maham"}}]},
            {"mode": "command", "executed": True,
             "answers": [{"name": "find_file", "arguments": {"query": "kollect deck"}}]},
            {"mode": "command", "executed": False,
             "answers": [{"name": "find_file", "arguments": {"query": "ignored ignored"}}]}]
    sug = dict(vocab.suggest(rows, existing=["Whistle"]))
    assert sug.get("Maham") == 2
    assert "ignored" not in sug
