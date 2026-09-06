"""Worker configuration and the tuning constants that matter."""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
EVENTS_CHANNEL = "transcribe:events"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

HF_TOKEN = os.environ.get("HF_TOKEN") or None

SAMPLE_RATE = 16_000

# --- ASR --------------------------------------------------------------------
ASR_MODEL = os.environ.get("ASR_MODEL", "large-v3")
ASR_COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8_float16")
ASR_BATCH_SIZE = int(os.environ.get("ASR_BATCH_SIZE", "8"))
LANGUAGE = "de"

# Empty on purpose.
#
# A liturgical vocabulary prime looked like an obvious win, and it actively
# backfired in testing: over a passage Whisper was unsure about, it emitted the
# prompt itself as the transcript - "Begruessung, Lesung, Predigt, Fuerbitten,
# Vaterunser, ..." - with avg_logprob -0.12, i.e. high confidence, so none of the
# threshold filters caught it. A comma-separated word list is the worst possible
# shape here: it is exactly what a decoder falls back on.
#
# large-v3 already knows German liturgical vocabulary. If you do set this, use a
# natural sentence rather than a word list, and keep it short - the prompt-echo
# filter in hallucinations.py will catch verbatim regurgitation either way.
INITIAL_PROMPT = os.environ.get("ASR_INITIAL_PROMPT", "").strip() or None

# --- Diarization ------------------------------------------------------------
DIARIZATION_MODEL = os.environ.get(
    "DIARIZATION_MODEL", "pyannote/speaker-diarization-community-1"
)
MIN_SPEAKERS = 1
MAX_SPEAKERS = 12

# --- Music detection --------------------------------------------------------
MUSIC_MODEL = os.environ.get("MUSIC_MODEL", "MIT/ast-finetuned-audioset-10-10-0.4593")
# AST was trained on ~10 s clips, so we classify 10 s windows and step 5 s.
# Hymns run for minutes; 5 s boundary resolution is far finer than needed and
# costs a tenth of what 1 s windows would.
MUSIC_WINDOW_S = 10.0
MUSIC_HOP_S = 5.0
MUSIC_BATCH = 16
# Soundboard feed: music and speech arrive on separate faders and barely bleed,
# so a confident absolute threshold is safe.
MUSIC_THRESHOLD = 0.45
# How far the music score must stand up to the speech score. Deliberately below
# 1.0: AudioSet's "Speech" class is extremely trigger-happy - in testing it read
# 0.796 on a 10 s window containing 0.4 s of actual speech, against 0.774 for
# Music on the organ that filled the rest of it. Requiring music to *beat*
# speech would suppress genuine hymns, especially congregational singing, which
# legitimately excites both classes.
MUSIC_OVER_SPEECH = 0.9
MUSIC_MIN_DURATION_S = 6.0
MUSIC_MERGE_GAP_S = 4.0

# AudioSet label -> German marker. Order matters: the first family that matches
# a window's top music label wins.
MUSIC_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("[Glocken]", ("Church bell", "Bell", "Bicycle bell", "Chime")),
    ("[Orgelspiel]", ("Organ", "Electronic organ", "Hammond organ", "Pipe organ")),
    ("[Gemeindegesang]", ("Singing", "Choir", "Chant", "Mantra", "Church music",
                          "Gospel music", "Hymn", "A capella")),
    ("[Applaus]", ("Applause", "Clapping")),
    ("[Musik]", ("Music", "Musical instrument", "Piano", "Keyboard (musical)",
                 "Guitar", "Brass instrument", "Trumpet", "Violin, fiddle",
                 "Flute", "Wind instrument, woodwind instrument", "Drum kit",
                 "Orchestra", "Classical music")),
]
SPEECH_LABELS = ("Speech", "Male speech, man speaking", "Female speech, woman speaking",
                 "Narration, monologue", "Conversation", "Child speech, kid speaking")

# --- VAD --------------------------------------------------------------------
# One VAD for both ASR gating and diarization masking. Using two different VADs
# is the documented cause of boundary hallucinations in diarized pipelines.
VAD_THRESHOLD = 0.5
VAD_MIN_SPEECH_MS = 250
VAD_MIN_SILENCE_MS = 500
VAD_SPEECH_PAD_MS = 200
VAD_MAX_SPEECH_S = 30.0

# --- Summary ----------------------------------------------------------------
LLM_ENABLED = os.environ.get("LLM_ENABLED", "false").lower() in {"1", "true", "yes"}
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:8b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
LLM_NUM_CTX = 8192
LLM_CHUNK_CHARS = 9000

# --- Waveform ---------------------------------------------------------------
PEAKS_PER_SECOND = 20


def job_dir(job_id: str) -> Path:
    return DATA_DIR / "jobs" / job_id
