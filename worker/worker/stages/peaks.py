"""Stage 2: precomputed waveform peaks.

The point of this stage is that her laptop must never decode the audio. We ship
min/max pairs and a duration; wavesurfer skips fetch-and-decode entirely and
just draws.

Values are int8 (-127..127) and the file is also written gzipped, which takes a
90-minute service from ~1.3 MB of JSON floats down to ~120 KB on the wire.
"""
from __future__ import annotations

import gzip
import json
import logging
import wave
from pathlib import Path

import numpy as np

from ..config import PEAKS_PER_SECOND

log = logging.getLogger(__name__)

_READ_FRAMES = 1 << 20


def run(wav_path: Path, out_dir: Path, duration: float) -> Path:
    with wave.open(str(wav_path), "rb") as handle:
        if handle.getsampwidth() != 2:
            raise RuntimeError("erwarte 16-bit PCM")
        rate = handle.getframerate()
        channels = handle.getnchannels()
        total_frames = handle.getnframes()

        samples_per_bucket = max(1, int(round(rate / PEAKS_PER_SECOND)))
        mins: list[int] = []
        maxs: list[int] = []
        carry = np.empty(0, dtype=np.int16)

        while True:
            raw = handle.readframes(_READ_FRAMES)
            if not raw:
                break
            block = np.frombuffer(raw, dtype="<i2")
            if channels > 1:
                block = block.reshape(-1, channels).mean(axis=1).astype(np.int16)
            block = np.concatenate((carry, block)) if carry.size else block

            usable = (block.size // samples_per_bucket) * samples_per_bucket
            carry = block[usable:].copy()
            if usable:
                buckets = block[:usable].reshape(-1, samples_per_bucket)
                mins.extend(buckets.min(axis=1).tolist())
                maxs.extend(buckets.max(axis=1).tolist())

        if carry.size:
            mins.append(int(carry.min()))
            maxs.append(int(carry.max()))

    # Interleave min,max per bucket. wavesurfer takes min and max over the
    # samples covering each pixel, so this reconstructs a proper two-sided
    # waveform at any zoom level.
    interleaved = np.empty(len(mins) * 2, dtype=np.float32)
    interleaved[0::2] = np.asarray(mins, dtype=np.float32)
    interleaved[1::2] = np.asarray(maxs, dtype=np.float32)

    scale = float(np.max(np.abs(interleaved))) or 1.0
    quantised = np.clip(np.round(interleaved / scale * 127.0), -127, 127).astype(np.int8)

    payload = {
        "version": 1,
        "duration": round(duration, 3),
        "pixels_per_second": PEAKS_PER_SECOND,
        "bits": 8,
        "samples_per_bucket": 2,
        "data": quantised.tolist(),
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    path = out_dir / "peaks.json"
    path.write_bytes(body)
    gz_path = out_dir / "peaks.json.gz"
    gz_path.write_bytes(gzip.compress(body, 6))

    log.info("peaks: %d buckets, %.0f KB raw / %.0f KB gz",
             len(mins), len(body) / 1024, gz_path.stat().st_size / 1024)
    return path
