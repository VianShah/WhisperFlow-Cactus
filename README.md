# Whistle Assistant

Offline, push-to-talk voice assistant for Windows, built on Cactus **Whistle**
(speech to text) and **Needle 3** (on-device tool calling). No API keys, no GPU,
no network at runtime. Full spec: [BUILD.md](BUILD.md).

**Status: Phase 2 (intent layer) built.** Dictation + voice commands `get_time` and
`open_app`. Phases 3–4 are placeholders.

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

### Commands (hold Ctrl+Alt+Space)

"What time is it?" and "Open notepad / chrome / spotify / VS Code". Apps must be
in `[apps.allowlist]` in `config.toml`; the model can only pick a name from that
list, and the program maps it to the configured executable.

Every command shows what was heard and what was done. Routing by the model's
confidence (thresholds in `config.toml`):

| Confidence | What happens |
|---|---|
| ≥ 0.75 | runs immediately |
| 0.45 – 0.75 | asks first: **press Ctrl+Alt+Space again** to confirm, **Esc** or wait 6 s to cancel |
| < 0.45, or no tool chosen | nothing runs; the transcript is shown |

Confirmation uses the hotkey rather than Enter/Y because those keystrokes would
also reach whatever app is focused.

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
- `cactus-needle` sends anonymous usage telemetry by default. This project turns
  it off (`NEEDLE_TELEMETRY=0`) and forces Hugging Face offline mode at runtime.

## Testing without Windows or a microphone (Linux / CI)

```bash
xvfb-run -a python tests/e2e_xvfb.py tests/fixtures/dictation_01.wav   # dictation
xvfb-run -a python tests/e2e_command_xvfb.py                           # Phase 2 gate
xvfb-run -a python tests/e2e_command_xvfb.py --confirm                 # confirm flow
```

This runs the real hotkey listener, Whistle, clipboard and Ctrl+V into a Tk text
box on a virtual display, and feeds a WAV file in place of the microphone.
Needs `xvfb xclip xdotool python3-tk`. The command harness puts a stub
`notepad.exe` on PATH, so a real process launch is checked without Windows.
