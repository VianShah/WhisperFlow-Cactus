"""Resolve a spoken time phrase ("tomorrow at six", "in 20 minutes") to a datetime.

Needle extracts the phrase; this module resolves it (spec 6, Phase 3: never ask
the model for ISO timestamps). dateparser alone was measured to be wrong on
spoken English ("tomorrow at six" -> tomorrow 19:50, "at 4" -> April next year,
"6 pm" -> a date in the past), so common spoken forms are handled by rules here
and dateparser is only a fallback for explicit dates ("november 5th").

Rules for a clock time with no am/pm: "morning" -> am; "afternoon", "evening",
"tonight" -> pm. With a day named ("tomorrow at six"): 1-6 -> pm, 7-11 -> am.
With no day ("at 8 30"): the next occurrence of that clock time, skipping
00:00-06:59 (nobody means 4 am without saying so). Results must be in the future and
within a year, else None: the caller refuses rather than guess.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty five": 25, "thirty": 30,
         "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
         "couple of": 2, "few": 3}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
UNITS = {"minute": 1, "min": 1, "hour": 60, "hr": 60, "day": 1440, "week": 10080}
NUM = r"(\d+|" + "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)) + r")"


def _num(s: str) -> int:
    s = s.strip()
    return int(s) if s.isdigit() else WORDS[s]


def _clean(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"\b(a\.m\.|a\.m|am)\b", " am", t)
    t = re.sub(r"\b(p\.m\.|p\.m|pm)\b", " pm", t)
    t = re.sub(r"(\d)(am|pm)\b", r"\1 \2", t)
    t = re.sub(r"[,.!?]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _relative(t: str, now: datetime):
    if re.search(r"\bhalf an? hour\b", t):
        return now + timedelta(minutes=30)
    m = re.search(r"\b(?:in )?" + NUM + r" (minute|min|hour|hr|day|week)s?\b", t)
    if m and (t.startswith("in ") or re.fullmatch(r"(?:in )?" + NUM + r" \w+s?", t)):
        return now + timedelta(minutes=_num(m.group(1)) * UNITS[m.group(2)])
    return None


def _clock(t: str):
    """-> (hour, minute, marker) or None. marker in {'am','pm',None}."""
    if re.search(r"\bnoon\b", t):
        return 12, 0, "pm"
    if re.search(r"\bmidnight\b", t):
        return 0, 0, "am"
    m = re.search(r"\b(half|quarter) (past|to) " + NUM + r"\b", t)
    if m:
        h = _num(m.group(3))
        mins = 30 if m.group(1) == "half" else 15
        if m.group(2) == "to":
            h, mins = (h - 1) % 12 or 12, 60 - mins
        return h, mins, _marker(t)
    m = re.search(r"\b(\d{1,2})[: ](\d{2})\b", t)
    if m:
        return int(m.group(1)), int(m.group(2)), _marker(t)
    m = re.search(r"\bat " + NUM + r"(?: " + NUM + r")?\b", t) or \
        re.search(r"\b" + NUM + r"(?: " + NUM + r")? ?(?:am|pm|o'?clock)\b", t)
    if m:
        h = _num(m.group(1))
        mins = _num(m.group(2)) if m.group(2) else 0
        if h <= 24 and mins < 60:
            return h, mins, _marker(t)
    return None


def _marker(t: str):
    if re.search(r"\bam\b|\bmorning\b", t):
        return "am"
    if re.search(r"\bpm\b|\bafternoon\b|\bevening\b|\btonight\b|\bnight\b", t):
        return "pm"
    return None


def _to24(h: int, marker) -> int:
    if h > 12:
        return h
    if marker == "am":
        return 0 if h == 12 else h
    if marker == "pm":
        return 12 if h == 12 else h + 12
    return h + 12 if 1 <= h <= 6 else h  # no marker: 1-6 pm, 7-12 as said


def _day(t: str, now: datetime):
    """-> (date, explicit) for today/tonight/tomorrow/weekday, else (None, False)."""
    if re.search(r"\bday after tomorrow\b", t):
        return (now + timedelta(days=2)).date(), True
    if re.search(r"\btomorrow\b", t):
        return (now + timedelta(days=1)).date(), True
    if re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", t):
        return now.date(), True
    for i, d in enumerate(DAYS):
        if re.search(rf"\b{d}\b", t):
            ahead = (i - now.weekday()) % 7
            if ahead == 0 or re.search(rf"\bnext {d}\b", t) and ahead < 7 and ahead == 0:
                ahead = 7
            return (now + timedelta(days=ahead)).date(), True
    return None, False


def resolve(phrase: str, now: datetime | None = None) -> datetime | None:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    t = _clean(phrase or "")
    if not t or re.search(r"\b(yesterday|ago|last)\b", t):
        return None
    result = _relative(t, now)
    if result is None:
        day, explicit = _day(t, now)
        clock = _clock(t)
        if clock:
            h, m, marker = clock
            if not explicit and marker is None and re.search(r"\bmorning\b", t):
                marker = "am"
            if explicit or marker is not None or h > 12:
                hh = _to24(h, marker)
                base = day or now.date()
                result = datetime(base.year, base.month, base.day, hh % 24, m)
                if not explicit and result <= now:
                    result += timedelta(days=1)
            else:
                result = _next_occurrence(h, m, now)
        elif explicit:
            part = re.search(r"\b(morning|afternoon|evening|tonight)\b", t)
            hh = {"morning": 9, "afternoon": 14, "evening": 18, "tonight": 20}.get(
                part.group(1) if part else "", 9)
            result = datetime(day.year, day.month, day.day, hh, 0)
        else:
            result = _dateparser_fallback(phrase, now)
    if result is None or result <= now or result > now + timedelta(days=366):
        return None
    return result


def _next_occurrence(h: int, m: int, now: datetime) -> datetime:
    cands = []
    for offset in (0, 1):
        d = now.date() + timedelta(days=offset)
        for hh in {h % 12, h % 12 + 12}:
            dt = datetime(d.year, d.month, d.day, hh, m)
            if dt > now and hh >= 7:
                cands.append(dt)
    return min(cands)


MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
          "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")


def _dateparser_fallback(phrase: str, now: datetime):
    # Only for explicit dates; dateparser turns bare numbers into nonsense dates.
    if not re.search(rf"\b({MONTHS})\b|\b\d{{1,2}}(st|nd|rd|th)\b|\d[/-]\d", phrase.lower()):
        return None
    try:
        import dateparser
    except ImportError:
        return None
    return dateparser.parse(phrase, settings={
        "PREFER_DATES_FROM": "future", "RELATIVE_BASE": now,
        "RETURN_AS_TIMEZONE_AWARE": False, "STRICT_PARSING": False})


TIMEISH = re.compile(r"^(at|in|on|this|next|tomorrow|today|tonight|morning|afternoon|"
                     r"evening|the|am|pm|o'?clock|half|quarter|past|to|noon|midnight|"
                     r"minutes?|hours?|days?|weeks?|an?|\d+(:\d+)?|" + "|".join(DAYS) + "|"
                     + "|".join(w for w in WORDS if " " not in w) + r")$")


def expand_from_transcript(when: str, transcript: str) -> str:
    """The model sometimes trims the phrase ("at 4" -> "4", "friday at 3pm" ->
    "friday"). Grow `when` inside the transcript over adjacent time words."""
    if not transcript or not when:
        return when
    toks, w = _clean(transcript).split(), _clean(when).split()
    n = len(w)
    for i in range(len(toks) - n + 1):
        if toks[i:i + n] != w:
            continue
        lo, hi = i, i + n
        while lo > 0 and TIMEISH.match(toks[lo - 1]):
            lo -= 1
        while hi < len(toks) and TIMEISH.match(toks[hi]):
            hi += 1
        span = toks[lo:hi]
        while span and span[0] in ("the", "to", "a", "an") and len(span) > n:
            span = span[1:]
        while span and span[-1] in ("to", "the", "a", "an", "in", "at", "on") and len(span) > n:
            span = span[:-1]
        out = " ".join(span)
        if len(out) > len(" ".join(w)) and resolve(out) is not None:
            return out
        return when
    return when


def grounded_in(when: str, transcript: str) -> bool:
    """Is the model's time phrase present in the transcript, allowing for the
    model writing number words as digits ("one minute" -> "1 minute")?"""
    def digits(t):
        t = _clean(t)
        for word, n in sorted(WORDS.items(), key=lambda kv: -len(kv[0])):
            if word in ("a", "an"):
                continue
            t = re.sub(rf"\b{re.escape(word)}\b", str(n), t)
        return t
    w = digits(when)
    return bool(w) and w in digits(transcript)
