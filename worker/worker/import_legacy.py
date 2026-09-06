"""Import recordings from the previous transcription system.

The old system stored a flat `db.json` alongside a directory of audio files. Its
entries already carry timestamped chunks, so there is nothing to gain from
putting 62 hours of audio back through the GPU - the text and the timings come
across as they are.

What still has to be produced is the two things the browser needs and the old
system never had: a 48 kbps Opus proxy for playback and precomputed waveform
peaks. Both are ffmpeg-and-numpy work, no models involved.

What imported jobs do *not* get, because the source has no such data: speaker
labels, music markers, and a summary. Re-running such a job through the normal
retry path would produce all three - at the cost of the full pipeline.

Usage (from the repo root):

    docker compose run --rm \
        -v "$PWD/migrate-stuff:/import:ro" \
        worker python -m worker.import_legacy --source /import

    --limit N            only the first N entries, for a trial run
    --jobs N             parallel ffmpeg workers (default 4)
    --originals copy     also copy the source file into the job directory
    --force              re-import entries that are already present
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from .config import DATA_DIR
from .stages import normalize, peaks

log = logging.getLogger("import")

API_URL = "http://api:8000"

# The old system wrote files named by bare UUID; some have no extension at all,
# so the container is probed rather than trusted.
_FORMAT_EXTENSIONS = {
    "mp3": ".mp3", "mov,mp4,m4a,3gp,3g2,mj2": ".mp4", "matroska,webm": ".mkv",
    "ogg": ".ogg", "flac": ".flac", "wav": ".wav", "aac": ".aac",
}


def legacy_job_id(legacy_id: str) -> str:
    """UUID with dashes -> the 32-hex form this app uses for job ids.

    Deriving the id from the source makes the whole import idempotent: the same
    entry always lands in the same job, so a re-run updates rather than
    duplicates.
    """
    return legacy_id.replace("-", "").lower()


def parse_created_at(value: str) -> tuple[str | None, str | None]:
    """'18.08.2023 23:12:22' -> (iso timestamp, date). Best effort."""
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            moment = datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
        return moment.isoformat(timespec="seconds"), moment.date().isoformat()
    return None, None


def nice_title(entry: dict[str, Any]) -> str:
    """A readable title from the old file name, minus extension and noise."""
    name = (entry.get("file_name") or "").strip()
    if not name:
        name = (entry.get("transcription_name") or "").split(" - ")[0].strip()
    stem = Path(name).stem if name else ""
    stem = stem.replace("_", " ").strip()
    return stem or "Importierte Aufnahme"


def probe_extension(path: Path) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=format_name",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    )
    return _FORMAT_EXTENSIONS.get(result.stdout.strip(), path.suffix or ".bin")


def build_transcript(entry: dict[str, Any], job_id: str,
                     duration: float) -> dict[str, Any]:
    segments = []
    for index, chunk in enumerate(entry.get("chunks") or []):
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        start = float(chunk.get("start") or 0.0)
        end = float(chunk.get("end") or start)
        segments.append({
            "id": f"s{index}",
            "type": "speech",
            "start": round(start, 3),
            "end": round(max(end, start), 3),
            "speaker": None,
            "text": text,
            "words": None,
        })
    if not segments and (entry.get("text") or "").strip():
        # No chunks, but there is text: keep it as one block rather than lose it.
        segments = [{"id": "s0", "type": "speech", "start": 0.0,
                     "end": round(duration, 3), "speaker": None,
                     "text": entry["text"].strip(), "words": None}]
    return {
        "version": 1,
        "job_id": job_id,
        "duration": round(duration, 3),
        "language": "de",
        "speakers": {},
        "segments": segments,
        # Marks the document as carrying no speakers or music markers, so the UI
        # can say so rather than looking like diarization simply failed.
        "source": "legacy-import",
    }


def import_entry(entry: dict[str, Any], audio: Path, *, copy_original: bool,
                 force: bool) -> str:
    job_id = legacy_job_id(entry["id"])
    directory = DATA_DIR / "jobs" / job_id
    transcript_path = directory / "transcript.json"

    if transcript_path.exists() and not force:
        # The media work is done, but registration happens after this file is
        # written - so a run that died in between would otherwise skip the entry
        # forever and never create its job row. Registering is idempotent and
        # cheap, so do it unconditionally and let re-runs converge.
        _register(_payload_for(entry, job_id, audio,
                               _duration_of(transcript_path),
                               directory if copy_original else None))
        return "skipped"

    directory.mkdir(parents=True, exist_ok=True)
    extension = probe_extension(audio)

    # normalize writes both the 16 kHz WAV and the Opus proxy in one decode. The
    # WAV is only needed to compute peaks - at ~110 MB per hour it is deleted
    # straight after, since no GPU stage will ever read it.
    source = directory / f"original{extension}"
    if copy_original:
        if not source.exists():
            shutil.copy2(audio, source)
        decode_from = source
    else:
        decode_from = audio

    _, _, duration = normalize.run(decode_from, directory)
    wav_path = directory / "audio.wav"
    try:
        peaks.run(wav_path, directory, duration)
    finally:
        wav_path.unlink(missing_ok=True)

    document = build_transcript(entry, job_id, duration)
    tmp = transcript_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    tmp.replace(transcript_path)

    _register(_payload_for(entry, job_id, audio, duration,
                           directory if copy_original else None))
    return "imported"


def _duration_of(transcript_path: Path) -> float:
    try:
        return float(json.loads(transcript_path.read_text(encoding="utf-8"))["duration"])
    except (OSError, ValueError, KeyError):
        return 0.0


def _payload_for(entry: dict[str, Any], job_id: str, audio: Path, duration: float,
                 original_dir: Path | None) -> dict[str, Any]:
    created_at, service_date = parse_created_at(entry.get("created_at", ""))
    payload = {
        "id": job_id,
        "title": nice_title(entry),
        "original_filename": entry.get("file_name") or f"{entry['id']}{audio.suffix}",
        "service_date": service_date,
        "duration_s": round(duration, 2),
        "size_bytes": audio.stat().st_size,
        "created_at": created_at,
    }
    if original_dir is not None:
        kept = next(iter(original_dir.glob("original.*")), None)
        if kept is not None:
            payload["original_path"] = str(kept)
    return payload


def _register(payload: dict[str, Any], attempts: int = 5) -> None:
    """POST the job row, retrying transient API outages.

    A batch of 121 recordings runs for half an hour. Restarting the API
    container in that window - or any brief blip - should cost one retry, not
    one lost recording that then has to be hunted down afterwards.
    """
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(f"{API_URL}/api/jobs/import", json=payload,
                                  timeout=60)
            response.raise_for_status()
            return
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            # 4xx means the payload is wrong; retrying will not help.
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise
            if attempt == attempts:
                raise
            log.warning("register %s failed (%s), retry %d/%d in %.0fs",
                        payload["id"], type(exc).__name__, attempt, attempts, delay)
            time.sleep(delay)
            delay *= 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="/import",
                        help="directory holding db.json and audio_files/")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=4,
                        help="parallel ffmpeg workers")
    parser.add_argument("--originals", choices=("skip", "copy"), default="skip",
                        help="'copy' duplicates the source audio into data/ "
                             "(the archive is ~12 GB); 'skip' keeps only the "
                             "Opus proxy")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s")

    source = Path(args.source)
    database = source / "db.json"
    audio_dir = source / "audio_files"
    if not database.exists():
        log.error("no db.json in %s", source)
        return 1

    entries = list(json.loads(database.read_text(encoding="utf-8"))["transcribes"].values())
    by_stem = {p.stem: p for p in audio_dir.iterdir() if p.is_file()}

    work, missing = [], []
    for entry in entries:
        audio = by_stem.get(entry["id"])
        (work.append((entry, audio)) if audio else missing.append(entry["id"]))
    if missing:
        log.warning("%d entries have no audio file and are skipped", len(missing))
    if args.limit:
        work = work[:args.limit]

    log.info("importing %d recordings with %d workers (originals: %s)",
             len(work), args.jobs, args.originals)

    counts = {"imported": 0, "skipped": 0, "failed": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(import_entry, entry, audio,
                        copy_original=args.originals == "copy",
                        force=args.force): entry
            for entry, audio in work
        }
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            entry = futures[future]
            try:
                counts[future.result()] += 1
            except Exception:
                counts["failed"] += 1
                log.exception("failed: %s (%s)", entry["id"], entry.get("file_name"))
            if done % 10 == 0 or done == len(futures):
                log.info("%d/%d  %s", done, len(futures), counts)

    log.info("done: %s", counts)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
