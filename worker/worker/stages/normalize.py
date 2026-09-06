"""Stage 1: decode whatever was uploaded into the two files everything else uses.

Both outputs come from a single ffmpeg invocation so the source is decoded once:

  audio.wav   16 kHz mono PCM, *no* dynamics processing - the pipeline audio.
              Music detection and VAD need to see true levels.
  audio.opus  48 kbps loudness-normalised mono - the browser playback proxy.
              ~30 MB for a 90-minute service instead of a gigabyte WAV.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Callable

from ..config import SAMPLE_RATE

log = logging.getLogger(__name__)

_PROGRESS_RE = re.compile(r"out_time_us=(\d+)")


class AudioError(RuntimeError):
    pass


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise AudioError(f"Datei konnte nicht gelesen werden: {result.stderr.strip()[:400]}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise AudioError("Dauer der Aufnahme konnte nicht bestimmt werden") from exc
    if duration <= 0:
        raise AudioError("Aufnahme enthaelt keine Audiodaten")
    return duration


def run(original: Path, out_dir: Path, on_progress: Callable[[float], None] | None = None,
        *, make_opus: bool = True) -> tuple[Path, Path, float]:
    """Decode to the pipeline WAV and (optionally) the playback proxy.

    `make_opus=False` exists for reprocessing an imported job, where the Opus
    proxy is itself the only source audio: writing it while reading it would
    destroy the file.
    """
    wav_path = out_dir / "audio.wav"
    opus_path = out_dir / "audio.opus"
    # Checked before any work: ffmpeg would truncate the source on open.
    if make_opus and original.resolve() == opus_path.resolve():
        raise AudioError("Refusing to overwrite the source audio")
    duration = probe_duration(original)

    command = [
        "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(original),
        # Pipeline audio: untouched levels.
        "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le", str(wav_path),
    ]
    if make_opus:
        # Playback proxy: loudness-normalised so quiet passages are audible on
        # laptop speakers.
        command += [
            "-map", "0:a:0", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ac", "1", "-c:a", "libopus", "-b:a", "48k", "-vbr", "on",
            "-application", "audio", str(opus_path),
        ]
    command += ["-progress", "pipe:1", "-nostats"]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        match = _PROGRESS_RE.search(line)
        if match and on_progress:
            on_progress(min(int(match.group(1)) / 1e6 / duration, 1.0))
    stderr = process.stderr.read() if process.stderr else ""
    if process.wait() != 0:
        raise AudioError(f"ffmpeg fehlgeschlagen: {stderr.strip()[:400]}")

    if not wav_path.exists() or wav_path.stat().st_size < 1024:
        raise AudioError("Aufbereitetes Audio ist leer")
    log.info("normalized %s -> %.1fs", original.name, duration)
    return wav_path, opus_path, duration
