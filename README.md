# Whistle Assistant

Offline, push-to-talk voice assistant for Windows, built on Cactus **Whistle**
(speech to text) and **Needle 3** (on-device tool calling). No API keys, no GPU,
no network at runtime. Full spec: [BUILD.md](BUILD.md).

**Status: Phase 4 in progress.** Dictation, 12 voice commands across four
families, tray icon, autostart, and the review → fine-tune → evaluate pipeline.
The production fine-tune is waiting on real data (see "Fine-tuning").

## Setup (Windows 10/11 x64, Python 3.11 or 3.12)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py --setup        # one-time model download (~50 MB), needs internet
python -m pytest -q
```

## Use

```powershell
python run.py                # hold Ctrl+Alt+D, speak, release -> text is pasted
python run.py --no-paste     # print transcripts only
python run.py --file a.wav   # transcribe a 16 kHz mono WAV, no mic needed
python run.py --text "open notepad"            # command path from typed text
python run.py --file a.wav --command --dry-run # decide + log, execute nothing
```

### Tray icon and autostart

A microphone icon sits in the system tray. Its colour shows the mode: grey
ready, blue dictating, green command, amber working, purple waiting for your
confirmation, red paused. Right-click for **Pause hotkeys**, **Start with
Windows**, **Open data folder** and **Quit**. Run with `--no-tray` to skip it.

```powershell
python run.py --autostart on      # Startup-folder shortcut (pythonw, no console)
python run.py --autostart status
python run.py --autostart off
```

### Commands (hold Ctrl+Alt+Space)

| Family | Say things like | Notes |
|---|---|---|
| Time | "What time is it?" | |
| Apps | "Open / close / switch to notepad, chrome, spotify, VS Code" | only apps in `[apps.allowlist]`; close = like clicking X (the app may ask to save) |
| System | "Set the volume to 30", "Mute the volume", "Lock the screen", "Turn off the display" | |
| Reminders | "Remind me to call mom tomorrow at six", "What are my reminders?", "Cancel reminder 3" | the exact resolved time is shown back; cancelling always asks first |
| Files | "Find my budget spreadsheet", then "Open result 2" | programs/scripts are shown in Explorer, never run |

Apps are matched by process name, so "switch to spotify" works even though
Spotify's window title is the song. Reminders use Windows Task Scheduler (or
Outlook, if installed) so they fire even if the assistant is closed; ones missed
while the PC was off fire at next startup. For instant file search install
[Everything](https://www.voidtools.com/) and put `es.exe` on PATH; otherwise the
assistant walks Documents/Desktop/Downloads, which is slower.

Every command shows what was heard and what was done. Routing by the model's
confidence (thresholds in `config.toml`):

| Confidence | What happens |
|---|---|
| ≥ 0.75 | runs immediately |
| 0.45 – 0.75 | asks first: **press Ctrl+Alt+Space again** to confirm, **Esc** or wait 6 s to cancel |
| < 0.45, or no tool chosen | nothing runs; the transcript is shown |

Confirmation uses the hotkey rather than Enter/Y because those keystrokes would
also reach whatever app is focused.

### Tuning: what to expect before fine-tuning (Phase 4)

Measured on the base Needle 3 model with `python tests/eval_intent.py` (60
commands, 5 per tool, plus 11 nonsense/unsafe phrases):

| | typed text | neural-voice audio → Whistle |
|---|---|---|
| right tool and arguments | 59/60 | 50–52/60 |
| …of those: runs immediately / asks first / refused (low confidence) | 29 / 13 / 17 | 21–25 / 11–15 / 13–19 |
| wrong action run without asking | **0** | **0** |
| nonsense that reached "asks first" | 0/11 | 0–1/11 |

Correct reminders and file searches mostly score 0.15–0.40, so with the
spec's thresholds they are **refused** and nothing happens. To have them offered
for confirmation instead, uncomment in `config.toml`:

```toml
[intent.confirm_floor]
set_reminder = 0.15
find_file = 0.15
```

This never makes anything run without your keypress. **It is enabled by
default** for those two tools. The real fix is the Phase 4 fine-tune on your
own `data/log.jsonl`.

### Fine-tuning (Phase 4)

1. Use the assistant normally; every command is logged.
2. Review what was logged; only reviewed rows are ever trained on:
   ```powershell
   python tools/review_log.py stats
   python tools/review_log.py review     # Enter=right, n=no tool, f=fix, d=drop
   ```
3. Export Needle's training format (optionally plus the cold-start seed set):
   ```powershell
   python tools/review_log.py export --seed-data tools/seed_examples.jsonl
   ```
4. Train. **Use the Cactus platform**, not a local run:
   ```powershell
   $env:NEEDLE_API_KEY = "..."   # cactuscompute.com/dashboard/api-keys
   needle platform finetune data/finetune/train.jsonl data/finetune/val.jsonl data/finetune/test.jsonl
   ```
   A local `needle finetune` LoRA works, but its model has **no confidence
   score**: every call reports `confidence: None` and the gate (correctly)
   refuses all commands. Only platform fine-tunes keep the confidence head. The
   platform run uploads your reviewed transcripts to cactuscompute.com and is
   billed; the assistant itself stays offline.

   Measured local LoRA run (cloud CPU, seed data only, 1 epoch, 98 steps,
   ~50 min, ~6 GB RAM, 63 MB `.cact`):

   | Model | Seed test split (49) | Default cases (60) | Nonsense safe | Usable by gate |
   |---|---|---|---|---|
   | Base Needle 3 | 30/49 | 59/60 | 5/5, 11/11 | yes |
   | Local LoRA | 33/49 | 58/60 | 5/5, 11/11 | **no** (`confidence: None`, all refused) |

   The gain is small (+3), it is trained only on synthetic seed phrases, and it
   introduced new wrong calls ("start the browser" → vscode, "exit code" →
   close notepad). Don't use a local fine-tune; wait for a few hundred reviewed
   real utterances and use the platform.
5. Compare before switching, then set `[intent] weights` in `config.toml`:
   ```powershell
   python tests/eval_intent.py --cases data/finetune/test.jsonl
   python tests/eval_intent.py --cases data/finetune/test.jsonl --weights path\to\tuned.cact
   ```

Grow keyword biasing from what you actually say:
`python tools/review_log.py vocab` (add `--apply` to append to `data/vocabulary.txt`).

Each utterance prints one line: transcript, audio length, STT time,
time-to-first-token, decode tokens/sec and release→text latency.

Everything you may want to change (hotkeys, thresholds, app allowlist, paste
timings) is in `config.toml`. Add names and jargon to `data/vocabulary.txt` to
improve recognition.

## Privacy

- Audio is processed in memory and discarded. No WAV files are written.
- `data/log.jsonl` stores **the transcript of every command** plus the model's
  parsed call, confidence and what was executed. It is the Phase 4 fine-tuning
  dataset (Needle's `query/tools/answers/reasoning` format). Dictated text is
  **not** logged unless you set `[log] include_dictation = true`. Delete the
  file at any time.
- `data/corrections.jsonl` holds your review verdicts; `data/finetune/` holds
  exported training files. Both contain transcripts and are git-ignored.
- `data/reminders.db` stores your reminder texts and times (cancelled ones are
  kept, marked cancelled). Delete it at any time. Scheduled tasks live under
  `WhistleAssistant\` in Task Scheduler and contain only a reminder number.
- `cactus-needle` sends anonymous usage telemetry by default. This project turns
  it off (`NEEDLE_TELEMETRY=0`) and forces Hugging Face offline mode at runtime.

## Testing without Windows or a microphone (Linux / CI)

```bash
xvfb-run -a python tests/e2e_xvfb.py tests/fixtures/dictation_01.wav   # dictation
xvfb-run -a python tests/e2e_command_xvfb.py                           # Phase 2 gate
xvfb-run -a python tests/e2e_command_xvfb.py --confirm                 # confirm flow
xvfb-run -a python tests/e2e_phase3_xvfb.py                            # four families
python tests/eval_intent.py [--voice]                                  # accuracy report
```

This runs the real hotkey listener, Whistle, clipboard and Ctrl+V into a Tk text
box on a virtual display, and feeds a WAV file in place of the microphone.
Needs `xvfb xclip xdotool python3-tk`. The command harnesses put stub
`notepad.exe` / `xdg-open` programs on PATH, so real process launches are
checked without Windows. Window control, volume, lock, display, toasts, Task
Scheduler and Outlook are Windows-only: they are unit-tested against fakes here
and **need checking on a real Windows PC**. For `--voice` with a human-like
voice, `pip install piper-tts`, download a Piper voice and set `PIPER_VOICE`.
