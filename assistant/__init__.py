"""Whistle Assistant: offline push-to-talk voice assistant."""
import os

# cactus-needle sends anonymous usage telemetry by default (needle/_telemetry.py).
# Spec 8.5 requires no outbound traffic at runtime, so disable it before any
# `import needle` anywhere in the process. setdefault lets a developer override.
os.environ.setdefault("NEEDLE_TELEMETRY", "0")
os.environ.setdefault("DO_NOT_TRACK", "1")
# After the one-time download, never let huggingface_hub reach the network.
# run.py --setup clears this to fetch the models.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
