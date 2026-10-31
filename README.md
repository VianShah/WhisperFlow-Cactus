# Whistle Assistant

Offline, push-to-talk voice assistant for Windows, built on Cactus **Whistle**
(speech to text) and **Needle 3** (on-device tool calling). No API keys, no GPU,
no network at runtime. Full spec: [BUILD.md](BUILD.md).

**Status: Phase 1 (dictation).** Phases 2–4 are placeholders.

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
```

Each utterance prints one line: transcript, audio length, STT time,
time-to-first-token, decode tokens/sec and release→text latency.

Everything you may want to change (hotkeys, thresholds, app allowlist, paste
timings) is in `config.toml`. Add names and jargon to `data/vocabulary.txt` to
improve recognition.

## Privacy

- Audio is processed in memory and discarded. No WAV files are written.
- `data/log.jsonl` (from Phase 2 on) stores **your transcripts** and the
  model's parsed commands, as a fine-tuning dataset. Delete it at any time.
- `cactus-needle` sends anonymous usage telemetry by default. This project turns
  it off (`NEEDLE_TELEMETRY=0`) and forces Hugging Face offline mode at runtime.

## Testing without Windows or a microphone (Linux / CI)

```bash
xvfb-run -a python tests/e2e_xvfb.py tests/fixtures/dictation_01.wav
```

This runs the real hotkey listener, Whistle, clipboard and Ctrl+V into a Tk text
box on a virtual display, and feeds a WAV file in place of the microphone.
Needs `xvfb xclip xdotool python3-tk`.
