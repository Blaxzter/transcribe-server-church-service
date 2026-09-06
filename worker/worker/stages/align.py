"""Stage 6: forced alignment to tighten word timestamps.

Whisper derives word times from decoder cross-attention, which is good to
roughly a tenth of a second. That is fine for click-to-seek but loose at speaker
changes, where a word attributed to the wrong side of a turn boundary puts a
whole sentence under the wrong name.

This runs CTC forced alignment (torchaudio) with a German wav2vec2 model over
each segment. It is a refinement, not a requirement: every failure path falls
back to the Whisper timings rather than failing the job.
"""
from __future__ import annotations

import gc
import logging
import re
import unicodedata
from typing import Any, Callable

import numpy as np
import torch

from ..config import SAMPLE_RATE

log = logging.getLogger(__name__)

ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-german"
_PUNCT = re.compile(r"[^\w\s'’-]", re.UNICODE)
# Segments shorter than this carry no useful alignment signal.
_MIN_SEGMENT_S = 0.15
# ...and nothing legitimate is longer than this. wav2vec2 self-attention is
# quadratic in clip length, so one bogus multi-minute segment can stall the
# whole stage. Callers tighten bounds before we get here; this is the backstop.
_MAX_SEGMENT_S = 45.0


def run(audio: np.ndarray, segments: list[dict[str, Any]], device: torch.device,
        on_progress: Callable[[float], None] | None = None) -> list[dict[str, Any]]:
    if not segments:
        return segments
    try:
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    except ImportError:
        log.warning("transformers CTC classes unavailable; keeping Whisper timings")
        return segments

    try:
        processor = Wav2Vec2Processor.from_pretrained(ALIGN_MODEL)
        model = Wav2Vec2ForCTC.from_pretrained(ALIGN_MODEL).to(device).eval()
    except Exception:
        log.warning("could not load alignment model %s; keeping Whisper timings",
                    ALIGN_MODEL, exc_info=True)
        return segments

    vocab = {k.lower(): v for k, v in processor.tokenizer.get_vocab().items()}
    blank_id = processor.tokenizer.pad_token_id or 0
    delimiter_id = vocab.get("|")

    aligned = 0
    try:
        with torch.inference_mode():
            for index, segment in enumerate(segments):
                try:
                    words = _align_segment(segment, audio, model, vocab, blank_id,
                                           delimiter_id, device)
                except Exception:
                    log.debug("alignment failed for segment at %.1fs",
                              segment.get("start", 0), exc_info=True)
                    words = None
                if words:
                    segment["words"] = words
                    segment["aligned"] = True
                    aligned += 1
                if on_progress and index % 10 == 0:
                    on_progress(index / len(segments))
    finally:
        del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    log.info("align: %d of %d segments realigned", aligned, len(segments))
    return segments


def _normalize(word: str) -> str:
    word = unicodedata.normalize("NFC", word).lower().strip()
    word = _PUNCT.sub("", word)
    return word.strip()


def _align_segment(segment: dict[str, Any], audio: np.ndarray, model, vocab: dict[str, int],
                   blank_id: int, delimiter_id: int | None,
                   device: torch.device) -> list[dict[str, Any]] | None:
    start, end = float(segment["start"]), float(segment["end"])
    if not (_MIN_SEGMENT_S <= end - start <= _MAX_SEGMENT_S):
        return None

    original_words = [w for w in (segment.get("text") or "").split() if w.strip()]
    if not original_words:
        return None

    # Build the CTC target: the characters of each word, with the word-delimiter
    # token between words (that is how wav2vec2 was trained).
    targets: list[int] = []
    word_of_token: list[int] = []
    emitted: list[int] = []
    for word_index, word in enumerate(original_words):
        cleaned = _normalize(word)
        ids = [vocab[ch] for ch in cleaned if ch in vocab]
        if not ids:
            continue
        if targets and delimiter_id is not None:
            targets.append(delimiter_id)
            word_of_token.append(-1)
        targets.extend(ids)
        word_of_token.extend([word_index] * len(ids))
        emitted.append(word_index)
    if not targets or not emitted:
        return None

    clip = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
    if clip.size < SAMPLE_RATE // 20:
        return None

    tensor = torch.from_numpy(np.ascontiguousarray(clip)).float().unsqueeze(0).to(device)
    logits = model(tensor).logits
    log_probs = torch.log_softmax(logits, dim=-1).float().cpu()
    if log_probs.shape[1] < len(targets):
        # Not enough frames to host the target sequence; CTC would fail.
        return None

    target_tensor = torch.tensor([targets], dtype=torch.int32)
    alignment, scores = _forced_align(log_probs, target_tensor, blank_id)

    spans = _merge_tokens(alignment[0], scores[0], blank_id)
    if len(spans) != len(targets):
        return None

    seconds_per_frame = (end - start) / log_probs.shape[1]
    bounds: dict[int, list[float]] = {}
    confidence: dict[int, list[float]] = {}
    for span, word_index in zip(spans, word_of_token):
        if word_index < 0:
            continue
        span_start = start + span["start"] * seconds_per_frame
        span_end = start + span["end"] * seconds_per_frame
        if word_index in bounds:
            bounds[word_index][1] = span_end
        else:
            bounds[word_index] = [span_start, span_end]
        confidence.setdefault(word_index, []).append(span["score"])

    words: list[dict[str, Any]] = []
    for word_index, word in enumerate(original_words):
        if word_index not in bounds:
            continue
        low, high = bounds[word_index]
        scores_for_word = confidence.get(word_index) or [0.0]
        words.append({
            "word": word,
            "start": round(max(start, low), 3),
            "end": round(min(end, max(high, low + 0.01)), 3),
            "probability": round(float(np.exp(np.mean(scores_for_word))), 3),
        })
    return words or None


def _forced_align(log_probs: torch.Tensor, targets: torch.Tensor, blank_id: int):
    """torchaudio.functional.forced_align, tolerating signature differences.

    NOTE: torchaudio has deprecated this as part of moving into maintenance mode
    and plans to remove it in 2.9 (we pin 2.8). When that bites, the whole align
    stage is optional - `run()` already falls back to Whisper's own word
    timestamps on any failure, so the pipeline degrades rather than breaks. The
    replacement would be a small CTC Viterbi implementation or ctc-forced-aligner.
    """
    import torchaudio.functional as F
    return F.forced_align(log_probs, targets, blank=blank_id)


def _merge_tokens(alignment: torch.Tensor, scores: torch.Tensor,
                  blank_id: int) -> list[dict[str, Any]]:
    """Collapse the frame-level path into one span per target token."""
    spans: list[dict[str, Any]] = []
    frames = alignment.tolist()
    frame_scores = scores.tolist()
    index = 0
    while index < len(frames):
        token = frames[index]
        if token == blank_id:
            index += 1
            continue
        start = index
        total = 0.0
        count = 0
        while index < len(frames) and frames[index] == token:
            total += frame_scores[index]
            count += 1
            index += 1
        spans.append({"token": token, "start": start, "end": index,
                      "score": total / max(count, 1)})
    return spans
