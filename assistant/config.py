"""Loads config.toml. Everything a user may change lives there, not in Python."""
from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent


def load(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.toml"
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_vocabulary(cfg: dict) -> list[str]:
    rel = cfg.get("speech", {}).get("vocabulary_file", "data/vocabulary.txt")
    path = ROOT / rel
    if not path.exists():
        return []
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line)
    return words
