# Whistle Assistant — Build Specification

An offline, Windows-native voice assistant built on Cactus Whistle (speech-to-text) and
Needle 3 (on-device tool calling). No API keys. No network calls at runtime. No GPU.

This document is the complete build brief. It is written to be handed to a coding agent
(Claude Code) as the authoritative source for the project.

---

## 0. How to use this document

**You are the implementing agent. Read this whole file before writing any code.**

Rules of engagement:

1. **Build in phases.** Phase 1 must run end-to-end before Phase 2 begins. Do not
   scaffold all four phases at once.
2. **Verify the API before you build against it.** The `cactus-needle` package is new and
   moving fast. Section 3 records the API as published on the model cards at the time of
   writing. Before Phase 1, run `pip show cactus-needle`, then `python -c "import needle; help(needle)"`
   and confirm the function signatures match. **If they differ, the live package wins —
   update this document and tell the user what changed.**
3. **Never invent a Cactus API call.** If something in Section 3 is not documented here,
   check the real docs at <https://cactuscompute.com/blog/needle-python-docs> or the source
   at <https://github.com/cactus-compute/needle>. Do not guess method names.
4. **Stop at each phase gate** (Section 9) and let the user test before continuing.
5. **Honour the security rules in Section 8 without exception.** This program executes
   actions on the user's machine based on model output. The constraints there are not
   optional.

---

## 1. Goal

A push-to-talk voice assistant for Windows that:

- transcribes speech entirely on-device,
- turns transcripts into structured tool calls entirely on-device,
- executes four families of action: dictation, app/OS control, reminders, file search,
- works with the network cable unplugged,
- costs nothing to run.

**Non-goals for v1:** mobile support, always-on wake word, conversational chat,
multi-turn dialogue, any cloud fallback.

---

## 2. Architecture

```
┌──────────────┐
│  Hotkey      │  global hotkey, push-to-talk
└──────┬───────┘
       │ press → start capture, release → stop
┌──────▼───────┐
│  Audio       │  16 kHz mono PCM
└──────┬───────┘
       │
┌──────▼───────┐
│  Whistle     │  whistle.cact — 16.9 MB — speech → text
└──────┬───────┘
       │ transcript
       ├─────────────────────► DICTATION MODE: clipboard → Ctrl+V → done
       │
┌──────▼───────┐
│  Needle 3    │  needle3.cact — 8–29 MB — text → function_calls + confidence
└──────┬───────┘
       │ typed arguments
┌──────▼───────┐
│  Executors   │  Windows: launch / remind / search
└──────────────┘
```

Both models run in **one engine, one process**. Whistle and Needle share the same
`.cact` container, quantisation and kernels, so there is no second runtime to install.

Two modes, separated by two different hotkeys:

| Mode | Hotkey | Path |
|---|---|---|
| Dictation | `Ctrl+Alt+D` | Whistle → clipboard → paste |
| Command | `Ctrl+Alt+Space` | Whistle → Needle → executor |

Keeping these separate is a deliberate design decision. Dictation must never be
intercepted by the intent model — when the user is dictating prose into an email, a
sentence like "open the file" is text, not a command.

---

## 3. Ground truth: the Cactus API

Everything in this section is taken from the official model cards. Treat it as the
reference; verify it against the installed package before building.

Sources:
- <https://huggingface.co/Cactus-Compute/whistle>
- <https://huggingface.co/Cactus-Compute/needle3>
- <https://github.com/cactus-compute/needle>

### 3.0 Verified against the installed package (cactus-needle 3.2.8, 2026-10-31)

Checked by reading the installed source. Where this differs from 3.1–3.6, this
section wins.

| Item | Spec said | Package actually does | Consequence for the build |
|---|---|---|---|
| `needle.transcribe` | `(path, language, keywords, word_timestamps)` | `(audio, language=None, keywords=None, word_timestamps=False, weights=None)`; returns `text, language, ttft_ms, decode_tps` | Matches. Accepts float samples directly, so no temp WAV is needed. |
| `@needle.tool` | `@needle.tool` | also accepts `triggers=[...]` | Optional extra, can help tool retrieval. |
| `Needle(...)` | `Needle(tools=[...])` | adds `system`, `weights`, `tool_index_path`, `auto_date=True`, `generation`, `stateless=False` | Use `stateless=True`: otherwise every turn stays in context and the package warns that accuracy drops. |
| `Needle.run()` | returns calls + confidence | **executes your Python functions before returning**; signature `run(query, max_steps=8, max_new_tokens=512, strict=True)` | **The 8.1 confidence gate cannot use `run()`.** Use `Needle.complete(text)`, which returns `function_calls` + `confidence` without executing, then gate and dispatch ourselves. |
| Telemetry | not mentioned | **on by default**: sends anonymous usage events to a Supabase endpoint on every `run`/`complete` call | Violates 8.5. Disabled with `NEEDLE_TELEMETRY=0` (set in `assistant/__init__.py`). |
| Offline after first run | weights cached | weights come from Hugging Face via `huggingface_hub` | Also set `HF_HUB_OFFLINE=1` at runtime; `run.py --setup` clears it for the one-time download. |
| Fine-tuning (Phase 4) | lifts accuracy | **local fine-tunes drop the confidence head**; `confidence` becomes `None`. Only platform fine-tunes keep it | Phase 4 must either use the platform fine-tune or redesign the gate. With `None`, the gate refuses everything. |
| Off-topic requests | "return an empty list rather than a guess" | **only reliably true when arguments are constrained.** With two tools and `open_app(name: str)`, "purple monkey dishwasher" became `open_app("purple monkey dishwasher")` (confidence 0.15) and "open the pod bay doors" scored 0.80 | `open_app.name` is a `Literal` enum built from the allowlist. Measured: nonsense, "open photoshop" and "pod bay doors" all return `[]`; "open vs code" maps to `vscode`; app confidence rose from 0.57–0.83 to 0.84–0.96. |
| Extra response fields | not mentioned | `suppressed_calls` (e.g. negated requests: "don't open notepad"), `validation.ungrounded`, `validation.negation`, `reasoning`, `peak_ram_mb` | The gate refuses on ungrounded or negated calls even at high confidence. |
| Confidence on empty answers | not specified | confidence is for the *whole decision*: "delete all my files" returns `[]` with confidence 0.91 | Empty `function_calls` never acts, whatever the score. |
| Fine-tune data format | not specified | JSONL rows of `{query, tools, answers, reasoning}` | `data/log.jsonl` uses exactly these field names. |
| Tool retrieval (12 tools) | keep schemas terse | `@needle.tool(triggers=[...])` matters a lot. Measured on 42 commands: right tool 31 → 41, wrong calls with confidence ≥ 0.75: 5 → 0. A system prompt made no difference. | Every tool has triggers (see `intent.py`). |
| Confidence on correct calls | calibrated | correct `set_reminder` / `find_file` calls mostly score 0.15–0.40, so the 8.1 gate refuses them | Optional `[intent.confirm_floor]` per tool (only refuse→confirm, never auto-run). Default off. Phase 4 fine-tune is the real fix. |
| Grounding check | not mentioned | flags `set_reminder.when` when the model writes "one minute" as "in 1 minute" | For that one field we use our own check (number words → digits); all other flags still refuse. |
| Transcript punctuation | not mentioned | "Set the volume to 50." → no tool (0.00); without the final "." → `set_volume` (0.96) | Final `.?!` is stripped before Needle. Lower-casing everything was worse. |
| Integer args | typed | `set_volume.level` sometimes arrives as a string (`"30"`, `"mute"`) | Executors coerce and validate; "mute"/"max" map to 0/100. |
| Date parsing (6.3) | `dateparser` or `dateutil` | `dateparser` is wrong on spoken times: "tomorrow at six" → tomorrow 19:50, "at 4" → April next year, "6 pm" → a past date | `assistant/timeparse.py`: rules for spoken forms, dateparser only for explicit dates, result must be future and < 1 year. |
| `open_file(path)` (6.3) | path from a prior `find_file` | a path cannot be spoken, and the agent is stateless | `open_file(number)` indexes the last results, so the rule is structural. Executable types are revealed in Explorer, never opened (opening = running). |
| `schtasks` | wake-up for reminders | `/SD` date format depends on the Windows locale | Tasks are registered from XML (`/XML`), ISO times, `StartWhenAvailable`. |
| Fine-tune routes (Phase 4.3) | "follow the fine-tuning blog post" | `needle finetune` = local LoRA on JAX (needs `cactus-needle[train]` + 242 MB `needle3.safetensors`; runs on CPU, ~6 GB RAM measured); `needle platform finetune` = cactuscompute.com, needs `NEEDLE_API_KEY`, billed | **Local LoRA output has no confidence head** → `confidence: None` → the 8.1 gate refuses everything. Production fine-tunes must use the platform. Local runs are only for measuring accuracy. Measured 1-epoch local LoRA on seed data: 33/49 vs base 30/49 (strict args) on the held-out split, 58/60 vs 59/60 on default cases, confidence None. |
| `needle` CLI telemetry | n/a | the CLI (`needle download`, `needle finetune`) also sends usage events unless `NEEDLE_TELEMETRY=0` is set in the shell | Set it in the shell for dev commands; the app sets it itself. |
| pystray on X11 | n/a | titles are encoded as Latin-1: "—" and "…" crashed the tray | ASCII-only tray text; tray updates can never raise into the hotkey path. |
| Mic capture | capture 16 kHz natively | the package's own mic code opens at the device's native rate and resamples with soxr | `audio.py` asks for 16 kHz first and falls back to native rate + soxr only if the device refuses. |

### 3.1 Install

```sh
pip install cactus-needle
```

A 16 kHz WAV or raw samples need nothing beyond the base install. **Other sample rates
and microphone capture need the `[mic]` extra:**

```sh
pip install "cactus-needle[mic]"
```

Both models are Apache 2.0. The engine and weights are fetched once on first use and
then cached, so the first run needs internet; every run after that is fully offline.

### 3.2 Whistle — transcription

```python
import needle

result = needle.transcribe("clip.wav")
print(result["text"])
```

Every call returns the text, the detected language, the milliseconds to the first token,
and the decoder's tokens per second after it.

Options:

| Argument | Effect |
|---|---|
| `word_timestamps=True` | adds each word with start, end and probability |
| `keywords=[...]` | biases the decoder toward names, places, jargon |
| `language="en"` | forces a language instead of auto-detecting |

`needle.Whistle()` is the same model as an object, used for `embed(audio)` or to hold a
fine-tuned `.cact`.

CLI, useful for manual testing:

```sh
needle whistle playground     # transcribe live from the microphone
needle whistle compare        # Whistle vs Whisper vs Moonshine on one clip
```

**Audio requirements:** 16 kHz mono. One pass up to 30 seconds, windowed beyond that.

**Languages:** English, German, French, Spanish, Italian, Dutch, Polish. Nothing else.
Set `language="en"` explicitly — this project is English-only and skipping detection is
faster and more reliable.

**Critical behaviour:** silence and steady noise return an empty transcript rather than
an invented sentence. But other sounds — music especially — can still come out as text.
This is why v1 is push-to-talk, not always-on.

### 3.3 Needle 3 — tool calling

```python
import needle

@needle.tool
def get_weather(city: str):
    "Get the current weather for a city."
    return {"city": city, "temp_c": 27, "sky": "clear"}

agent = needle.Needle(tools=[get_weather])
print(agent.run("what's it like in Lagos right now?")["results"])
```

The decorator does the work: **the function signature gives the argument types, and the
docstring is the tool description.** `run()` completes the loop — it selects the tool,
fills the arguments, executes your function and returns the results.

Every turn returns one JSON object containing:

| Field | Meaning |
|---|---|
| `function_calls` | the calls the model chose, in order |
| `results` | what your functions returned |
| `reasoning` | the model's reasoning |
| `confidence` | a calibrated score from a learned head |

**An off-topic request returns an empty list rather than a guess.** This is the single
most important safety property of the model — it will not invent a tool it does not have.

### 3.4 Context budget — read this before designing tools

Tool schemas share the model's context with the system prompt and the conversation.
Initialisation fails if the static prefix does not fit.

The mitigation is built in: **declare more than five tools and Needle keeps only the
retrieved tools in the per-turn prefix.** Our design has roughly a dozen tools, so this
path is active and intended. Keep tool descriptions short regardless.

Also note `max_new_tokens` reserves context room at completion time — a large generation
cap leaves less space for the current turn.

### 3.5 Combined speech-to-tool-call

The engine can do both at once, transcribing and answering against your tools in a
single call, returning one JSON object with the speech fields prefixed `audio_`:

```sh
needle --model needle3.cact --model whistle.cact --tools tools.json --audio clip.wav
```

**Do not use this for v1.** Keep the two stages separate in Python so you can log the
transcript, apply keyword biasing, and debug the intent layer independently. Revisit the
combined call as a latency optimisation in Phase 4 only if it is needed.

### 3.6 Known accuracy limits — design around these

On public benchmarks, Needle 3's out-of-the-box tool calling is middling: roughly 50% on
BFCL v4, behind several models in the 0.8–1.2B range, and 47% on DroidCall against
DeepSeek V4 Flash's 60.5%.

This is expected and does not block the project, for two reasons:

1. We have ~12 fixed tools, not an open benchmark.
2. The model is explicitly designed to be fine-tuned on a specific product's tool set,
   and fine-tuning on DroidCall lifted every subnetwork by 18 to 36 points.

**Implication for the build:** log every `(transcript, function_calls, confidence)`
triple from day one, in JSONL. That log becomes the fine-tuning dataset in Phase 4.
Needle fine-tunes on 100–10,000 examples. Not collecting this from the start is the
most expensive mistake available in this project.

---

## 4. Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10 or 11, x64 | `cactus-needle` ships wheel-tagged engines for Windows x64 and ARM |
| Python 3.11 or 3.12 | avoid 3.13 until wheel availability is confirmed |
| A working microphone | check Windows sound settings first |
| ~100 MB disk | both models plus engine |
| Internet, once | to fetch engine and weights on first run |

Optional but strongly recommended:

- **Everything** by voidtools, with its CLI `es.exe` — <https://www.voidtools.com/>
  This is the best file search available on Windows and makes Phase 3's search tool
  trivial. Install it and add `es.exe` to PATH before starting Phase 3.

---

## 5. Project layout

```
whistle-assistant/
├── README.md
├── requirements.txt
├── config.toml                 # hotkeys, paths, allowlist, thresholds
├── run.py                      # entry point
├── assistant/
│   ├── __init__.py
│   ├── audio.py                # capture, 16 kHz mono
│   ├── stt.py                  # Whistle wrapper + keyword biasing
│   ├── intent.py               # Needle agent, tool registry
│   ├── hotkeys.py              # global hotkey listener
│   ├── logbook.py              # JSONL logging for fine-tuning
│   ├── notify.py               # Windows toasts
│   └── tools/
│       ├── __init__.py
│       ├── dictation.py
│       ├── apps.py
│       ├── reminders.py
│       └── files.py
├── data/
│   ├── vocabulary.txt          # keyword biasing list
│   └── log.jsonl               # transcript + intent log
└── tests/
    ├── fixtures/*.wav
    └── test_*.py
```

---

## 6. Build phases

### Phase 1 — Dictation (build this first)

**Why first:** it needs no intent layer at all, it proves the entire audio pipeline, and
it is the feature the user will touch fifty times a day. If Phase 1 is not pleasant to
use, nothing later will be.

Implement:

1. `requirements.txt` with `cactus-needle[mic]`, `pynput`, `pyperclip`.
2. Global hotkey listener on `Ctrl+Alt+D`. Use `pynput` rather than the `keyboard`
   package — `keyboard` frequently requires elevation for global hooks on Windows.
3. Push-to-talk capture: key down starts recording, key up stops. Capture at 16 kHz mono
   directly; do not record at 44.1 kHz and resample.
4. Transcribe with `needle.transcribe(path_or_samples, language="en", keywords=vocab)`.
5. Insert the text **via the clipboard**: save the current clipboard, set the transcript,
   send `Ctrl+V`, then restore the original clipboard after a short delay.
   Do not use synthetic per-character keystrokes — they are slow and mangle punctuation
   and unicode.
6. A console line per utterance: transcript, latency, tokens/sec.

**Phase 1 gate:** the user can hold `Ctrl+Alt+D`, speak a sentence into any text box in
any application, release, and see correct text appear. Measure and report end-to-end
latency. Then stop.

### Phase 2 — Intent layer

1. Build the tool registry in `intent.py` using `@needle.tool`. Start with exactly two
   trivial tools to validate the loop — e.g. `get_time()` and `open_app(name)`.
2. Second hotkey `Ctrl+Alt+Space` routes to the command path.
3. Wire the confidence gate from Section 8.1 **before** adding any real tools.
4. Start writing `data/log.jsonl` on every utterance.
5. Speak the toast feedback: every command must produce visible confirmation of what the
   assistant believed it heard and what it did.

**Phase 2 gate:** "what time is it" and "open notepad" both work, and a nonsense phrase
produces an empty `function_calls` list with no action taken.

### Phase 3 — The four action families

Implement in this order. Each tool is one action, named the way the user would say it.

**`apps.py` — open apps and control the OS**

- `open_app(name: str)` — resolve `name` against an **allowlist** in `config.toml`
  mapping spoken names to executables. Never pass the model's string to a shell.
- `close_window(name: str)`, `focus_window(name: str)` via `pygetwindow`.
- `set_volume(level: int)`, `lock_screen()`, `sleep_display()`.

**`reminders.py` — reminders and calendar**

Windows has no clean local reminders API. Two viable paths:

- *Default:* SQLite store + `schtasks` for the wake-up, so reminders survive reboot, plus
  a toast via `win11toast` when they fire.
- *If the user lives in Outlook:* `pywin32` COM against Outlook's calendar. Detect
  Outlook's presence at startup and choose automatically; log which path was taken.

Tools: `set_reminder(text: str, when: str)`, `list_reminders()`, `cancel_reminder(id: int)`.

Parse `when` with `dateparser` or `python-dateutil` — do **not** ask Needle to emit an
ISO timestamp. Small models are unreliable at date arithmetic. Let the model extract the
phrase "tomorrow at six" and let a proper date library resolve it. Always echo the
resolved absolute time back in the confirmation toast.

**`files.py` — file search**

- Primary: shell out to Everything's `es.exe` and parse results. Instant, no index to
  build, no permissions fights.
- Fallback if `es.exe` is absent: `os.walk` over a configured list of folders, with a
  result cap and a timeout. Warn the user it will be slow and point them at Everything.

Tools: `find_file(query: str, limit: int = 10)`, `open_file(path: str)`.

`open_file` must validate that the path came from a prior `find_file` result in this
session. Do not open arbitrary model-supplied paths.

**Phase 3 gate:** all four families work by voice. The log has at least 50 real
utterances in it.

### Phase 4 — Polish (only after 1–3 are solid)

In priority order:

1. System tray icon with mode indicator and a quit option (`pystray`).
2. Autostart via a Startup folder shortcut or a scheduled task.
3. Fine-tune Needle on `data/log.jsonl` once it holds a few hundred corrected examples.
   Follow <https://cactuscompute.com/blog/finetuning-needle>. Expect a large accuracy
   jump; this is the intended path, not an optimisation.
4. Grow `data/vocabulary.txt` from the log — every app name, contact name and command
   verb the user actually says. Keyword biasing is the cheapest accuracy win available.
5. *Optional:* a wake word, which requires a VAD in front of the microphone. Only
   attempt this after everything else is stable, and keep push-to-talk as the default.
6. *Optional:* collapse the two-stage pipeline into the single combined engine call
   (Section 3.5) if latency measurements justify it.

---

## 7. Configuration

`config.toml` holds everything the user might reasonably change, so they never have to
edit Python:

```toml
[hotkeys]
dictate = "ctrl+alt+d"
command = "ctrl+alt+space"

[speech]
language = "en"
max_seconds = 30
vocabulary_file = "data/vocabulary.txt"

[intent]
act_threshold = 0.75        # above this, execute silently
confirm_threshold = 0.45    # between the two, ask first; below, refuse

[apps.allowlist]
notepad = "notepad.exe"
chrome  = "chrome.exe"
vscode  = "code"
spotify = "spotify.exe"

[files]
everything_cli = "es.exe"
fallback_roots = ["C:/Users/%USERNAME%/Documents", "C:/Users/%USERNAME%/Desktop"]
```

---

## 8. Security rules — non-negotiable

This program converts speech into actions on a personal machine. A misheard word must
never become a destructive operation.

### 8.1 Confidence gating

Needle returns a calibrated `confidence` on every turn. Route on it:

- `confidence >= act_threshold` → execute, show a toast saying what was done.
- `confirm_threshold <= confidence < act_threshold` → show the parsed intent and require
  an explicit confirmation keypress before executing.
- `confidence < confirm_threshold` → refuse, show the transcript, do nothing.
- `function_calls == []` → do nothing. Show the transcript so the user can see what was
  heard. Never fall back to a fuzzy string match when the model declines to act.

### 8.2 No shell interpolation, ever

Tools take **typed arguments**, never a command string. There must be no code path where
a transcript or a model-generated string reaches `subprocess` with `shell=True`,
`os.system`, `eval` or `exec`.

The allowlist pattern in `apps.py` is the model to follow throughout: the model chooses a
*key*, the program maps that key to a *pre-approved value*.

### 8.3 Destructive actions

v1 ships **no** delete, move, overwrite, or "send" tool. Opening, searching, launching
and reminding only. If the user later asks for a delete tool, it gets a mandatory
confirmation step independent of the confidence score.

### 8.4 Privacy

Audio is processed in memory and discarded. Do not write WAV files to disk except
explicitly into `tests/fixtures/` during development. `data/log.jsonl` contains
transcripts — document this clearly in the README so the user knows it exists and can
delete it.

### 8.5 Offline verification

Once the models are cached, the assistant must work with networking disabled. Add a test
that asserts no outbound socket is opened during a full command cycle. If Cactus exposes
any cloud-handoff setting, disable it explicitly rather than relying on the default.

---

## 9. Phase gates

Do not proceed past a gate without the user confirming.

| Gate | Criterion |
|---|---|
| 1 | Dictation works in any application. Latency measured and reported. |
| 2 | Two trivial tools fire correctly. Nonsense input produces no action. |
| 3 | All four action families work by voice. 50+ logged utterances. |
| 4 | Tray icon, autostart, and a fine-tune run completed. |

---

## 10. Testing

- **Fixtures:** record 20 short WAVs covering every intent, plus silence, plus background
  music. Assert silence returns empty text and music does not trigger an action.
- **Intent tests:** 5 phrasings per tool. Assert the right tool and the right arguments.
- **Executor tests:** mock every Windows call. No test should actually open Spotify.
- **Airplane-mode test:** the manual check that matters most. Disable the adapter and run
  a full cycle.

---

## 11. Known pitfalls

| Pitfall | Avoidance |
|---|---|
| Recording at 44.1 kHz | Capture 16 kHz mono natively; Whistle expects it |
| Using the `keyboard` package | Needs elevation for global hooks; use `pynput` |
| Per-character keystroke injection | Use clipboard + `Ctrl+V` |
| Asking Needle for ISO timestamps | Extract the phrase, resolve with a date library |
| Declaring 5 or fewer tools | Tool retrieval activates above five; keep schemas terse |
| Walking the filesystem for search | Use Everything's `es.exe` |
| Not logging from day one | The log is the fine-tuning dataset; start it in Phase 2 |
| Assuming the API from memory | It is weeks old; verify against the installed package |
| Always-on microphone in v1 | Music transcribes as text; stay push-to-talk |

---

## 12. First actions for the implementing agent

1. Confirm Python version and OS architecture.
2. Create the venv and `pip install "cactus-needle[mic]"`.
3. Run `needle whistle playground` and confirm microphone transcription works at all,
   before writing a single line of project code. If this fails, stop and diagnose —
   nothing downstream can work.
4. Verify the API in Section 3 against the installed package. Report any differences.
5. Scaffold the layout in Section 5.
6. Build Phase 1. Stop at the gate.
