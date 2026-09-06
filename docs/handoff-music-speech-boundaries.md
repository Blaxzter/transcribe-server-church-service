# Handoff: words lost at music/speech boundaries

Written at the end of the session that built the pipeline, for whoever picks up
this specific bug. Everything here was measured on real recordings, not reasoned
about — where a number appears, it came from running the thing.

## The problem

A few words are cut where speech meets music. Most visible on
`7cfcf258151a411da7edd6d852fd19dc` (*2026-08-27 R. Gerhardt*, 72.7 min), where it
happens at nearly every boundary.

Measured against that recording's pre-pipeline transcript: **26 words, 0.4% of
the text**, in fragments cut mid-phrase.

| when | fragment lost |
|---|---|
| 1246.6 s | "und das hier ist euer" |
| 1621.6 s | "und wenn wir auf ein fest der begegnung zugehen das" |
| 2095.0 s | "empfange den segen des herrn und" |
| 3696.2 s | "manchmal ist es aber auch" |

They read like the head or tail of a sentence, which is what points at boundary
handling rather than at recognition.

## Current baseline for that job

Reproduce these before changing anything; a fix must not move them the wrong way.

| | |
|---|---|
| segments | 313 (306 speech, 7 music) |
| words | 6540 |
| speakers | 7 |
| hallucinations | 0 |
| VAD | 566 regions, 41.6 min of speech in 72.7 min |
| music regions | 0.1–3.9, 6.4–8.5, 8.6–11.8, 29.1–31.1, 31.5–33.9, 35.5–37.1, 69.4–72.7 min |
| unexplained loss | 26 words (0.4%) |

Reprocess with `POST /api/jobs/<id>/retry`; about 15 minutes on the 8 GB GPU.

## Where boundaries are decided

All in `worker/worker/stages/`, plus two constants in `worker/worker/config.py`.

1. **`vad.py`** — `VAD_SPEECH_PAD_MS` (200 ms) pads each detected speech region.
   A word beginning just before the pad falls outside the region entirely.
   `VAD_MIN_SILENCE_MS` (500 ms) decides where a region ends at all.
2. **`merge.split_across_speech`** — *the prime suspect.* A merged ASR segment is
   spread over the speech runs it spans, with words allocated **in proportion to
   each run's duration**. That is a heuristic, and it is at its weakest exactly
   at the joins, which is where the losses are.
3. **`merge.clip_to_speech`** — the single-run case; truncates a segment at the
   end of the run it starts in. `_SPEECH_BRIDGE_SECONDS` (8 s) decides what
   counts as one run.
4. **`merge._music_without_speech`** — clips music regions off transcribed
   speech. Moves the visible boundary, not the word list, so it changes what a
   reader sees but cannot itself lose words.

## What has already been tried, and how each failed

Do not repeat these. Each looked right and was wrong in a way only measurement
exposed.

**Truncating at the first VAD gap, 2 s threshold.** Recovered a lost
announcement and silently deleted 193 words: two sermon segments lost their tails
at **2.9 s and 2.5 s pauses** — a preacher pausing for effect, read as the end of
the utterance.

**Raising the threshold to 8 s.** Chosen from the gap distribution across three
services: ordinary speaking pauses have a 90th percentile of 1.5–2.3 s, while the
gaps that must be cut are 20 s and up. This is why the constant is 8 and not
something rounder. Note the distribution is *not* cleanly bimodal on every
service — Gerhardt has 19 gaps in the 4–30 s band.

**Truncation itself.** Even at 8 s it discarded the tail of a merged segment,
which is real speech from a *later* run, not noise. That lost *"Lieber Daniel,
lieber Stefan, ihr lieben Jugendlichen…"*. Replaced by the proportional
redistribution now in place, which took Gerhardt from 201 unexplained words to 26
and Schermutzki from 476 to **0**.

**Halving `MUSIC_HOP_S` for finer resolution.** Considered and rejected on
evidence: inside a musical passage the AudioSet speech score sits at 0.003–0.018
for minutes at a time. Resolution is not the problem; boundaries are.

## Traps

- **Word timings inside a merged segment are themselves unreliable.**
  faster-whisper's batched pipeline collapses the audio the VAD removed, so a
  segment can claim to span 13 minutes with its words stretched to match.
  `merge.tighten_bounds` cannot rescue that. Anything that trusts those timings
  at a boundary will look correct and be wrong. This is the single biggest trap
  here and it cost two attempts.
- **Over-trimming is silent; under-trimming is caught downstream** by the
  music-overlap check. The two failure modes are not symmetric, so when in doubt
  keep more.
- **Word counts hide losses.** A fix can add and remove words simultaneously. Use
  a sequence diff.
- **Classify the diff run, not its source segment.** Doing the latter attributed
  multi-segment repetition loops to real loss and produced a 476-word figure that
  was almost entirely false. Judge the text of the run itself.
- Segments carry `aligned: false` on words forced alignment could not place
  (digits are absent from the wav2vec2 vocabulary). Their timings are
  interpolated between neighbours and are approximate by construction.

## How to measure a fix

The honest metric is a sequence diff against the recording's previous
transcript, with every old-only run of 5+ words classified as one of:

- **looping in the old system** — the run's own vocabulary is heavily repeated
  (unique/total below about 0.45). Correctly absent.
- **inside detected music** — falls within a region in `music.json`. Sung lyrics,
  absent by design.
- **unexplained** — everything else. *This is the bug.* Currently 26 words on
  Gerhardt, 0 on Schermutzki.

A fix should shrink the unexplained bucket without growing the others, and must
leave hallucinations at 0, the seven music regions intact, and the speaker count
unchanged.

## What is on disk

Every stage keeps its raw output per job under `data/jobs/<id>/`, so a boundary
can be inspected without re-running anything on the GPU:

| file | |
|---|---|
| `vad.json` | speech regions — the ground truth for where speech is |
| `music.json` | detected music regions |
| `music_windows.json` | per-window music/speech scores, 5 s resolution |
| `asr.json` | ASR segments *after* bound tightening, plus everything dropped and why |
| `diarization.json` | speaker turns |
| `transcript.json` | the finished document |

## Conventions

- Tests live in `tests/test_logic.py`; 127 pass today. Run them with
  `.\scripts\verify.ps1`, which also checks GPU passthrough and the containers.
- German for anything a user reads, English for identifiers and comments.
- Rebuild after worker changes: `docker compose build worker` then
  `docker compose --profile llm up -d worker`.
- Constants that encode a measurement carry the measurement in a comment. Keep
  that up if you change one — the numbers are why the value is what it is.
