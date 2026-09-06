# Transkript

Self-hosted German transcription server for church services, with speaker
diarization and music detection. Everything runs locally on one machine — no
audio ever leaves the box.

Built for a specific set of constraints: an **RTX 4070 Laptop (8 GB VRAM)**,
uploads arriving through an existing **Cloudflare Tunnel**, and a viewer on a
weak laptop that must never have to decode a gigabyte of audio.

---

## What it does

1. Accepts a recording of any length through a resumable, chunked upload.
2. Detects organ, hymns, congregational singing and bells, and labels those
   spans `[Orgelspiel]`, `[Gemeindegesang]`, `[Glocken]` instead of transcribing
   them — this is what stops Whisper hallucinating subtitle credits over music.
3. Transcribes the speech with `faster-whisper` large-v3.
4. Separates the speakers with `pyannote` community-1.
5. Produces an editable, speaker-labelled transcript with a waveform player,
   an optional local-LLM summary, and DOCX / MD / TXT / SRT / VTT export.

## Requirements

- Windows 11 with Docker Desktop (WSL2 backend) and a working NVIDIA driver
- A Hugging Face token (free) — pyannote community-1 is a gated model
- ~20 GB of disk for models, plus room for recordings

Verify GPU passthrough **before anything else**. If this does not print your
GPU, nothing downstream will work:

```powershell
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

## Setup

### 1. Hugging Face token

1. Create a read token at <https://hf.co/settings/tokens>
2. Accept the terms at <https://hf.co/pyannote/speaker-diarization-community-1>
3. Put it in `.env`:

```env
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
```

### 2. Start

```powershell
docker compose up -d          # without the summary model
docker compose --profile llm up -d   # with the local LLM summary
```

The first job downloads about 10 GB of models and will be slow. Everything after
that is fast. Models are cached in a named Docker volume, so they survive
rebuilds.

Open <http://localhost:8080>.

The summary stage needs **both** halves, and they fail quietly if you only do
one: set `LLM_ENABLED=true` in `.env` *and* start with `--profile llm`. With the
flag on but no `ollama` container, every job logs
`summary skipped: Ollama nicht erreichbar` and finishes without one. The first
summary pulls `qwen3:8b` (~5 GB), so that job takes a few minutes longer.

## Cloudflare wiring

The service is reached at **https://freddy-transcribe.fabraham.dev**.

The tunnel on this machine is **locally managed** and runs as a Windows service
under **LocalSystem**, reading its config from:

```
C:\Windows\System32\config\systemprofile\.cloudflared\config.yml
```

The copy in `C:\Users\<you>\.cloudflared\config.yml` is *not* the live file —
editing it has no effect. This trips people up.

SSH and HTTP cannot share a hostname, so `respeak-server.fabraham.dev` keeps its
SSH mapping untouched and the web UI gets its own hostname on the same tunnel.

### 1. DNS — done

```powershell
cloudflared tunnel route dns c9795d2c-6b4f-44be-99ce-f7a52a25dfe5 freddy-transcribe.fabraham.dev
```

A CNAME for `freddy-transcribe.fabraham.dev` already points at the tunnel.

### 2. Ingress rule — needs an elevated shell

```powershell
# In an Administrator PowerShell, from the repo root:
.\scripts\setup-tunnel.ps1
```

It backs up the live config, inserts the rule above the `http_status:404`
catch-all, validates with `cloudflared ingress validate`, restarts the service,
and restores the backup if validation fails. The resulting ingress:

```yaml
ingress:
  - hostname: respeak-server.fabraham.dev
    service: ssh://localhost:22
  - hostname: freddy-transcribe.fabraham.dev
    service: http://localhost:8080
    originRequest:
      connectTimeout: 30s
  - service: http_status:404
```

> Between this step and the next, the hostname is **public**. Do the two
> together, or do Access first.

### 3. Cloudflare Access — needs an API token

```powershell
$env:CLOUDFLARE_API_TOKEN = "..."   # not stored, not echoed
.\scripts\setup-access.ps1 -Emails "you@example.com","her@example.com"
```

Create the token at *My Profile → API Tokens → Create Token → Custom token*
with:

| Scope | Permission | Level |
|-------|-----------|-------|
| Account | Access: Apps and Policies | Edit |
| Account | Account Settings | Read |
| Zone | Zone | Read |

The script creates a self-hosted application for the hostname and an allow
policy restricted to those email addresses, with a **one-month session**
(`-SessionDuration`, see the note below on why). Login is by **one-time PIN**, so
there is no identity provider to set up: she gets a code by email.

Re-running it is safe; it reuses an existing application rather than duplicating.

Prefer clicking? Zero Trust → Access → Applications → Add a self-hosted
application for `freddy-transcribe.fabraham.dev`, one Allow policy with
*Emails* = both addresses, session duration one month. That is exactly what the
script does.

### Making login as easy as possible

The session duration matters more than the login method. It defaults to
**one month** (`730h`), which turns "fetch a code from your inbox every visit"
into "roughly once a month". On someone's own laptop that is the right trade.

| Method | Setup effort | What she does |
|---|---|---|
| **One-time PIN** (default) | none — built in | Types her email, opens her inbox, pastes a 6-digit code. Once a month. |
| **Google** | ~10 min, once | Clicks *Sign in with Google*. Usually zero further clicks, because the browser is already signed in. |

One-time PIN needs no identity provider at all, which is why it is the default.
Google is genuinely easier *for her* but costs you a Google Cloud Console
project with an OAuth client ID and secret
([setup guide](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/google/)).

The two can be enabled at the same time, so starting with PIN and adding Google
later breaks nothing — the policy is written against her email address either
way, and Google returns that same address.

Two practical notes: the PIN email can land in spam the first time, and the
address in the policy must be the one she actually reads on that laptop. Have
her bookmark the URL.

### 4. Check it

From a private browser window you should get a PIN prompt, and an address that
is not on the list should be refused. Access denies by default, so if no policy
matched, nobody gets in — including you.

### Why uploads are chunked

Cloudflare rejects any single proxied request body over **100 MB**. A 90-minute
service is far bigger, so the browser slices the file into 8 MB `PATCH` requests
using the tus protocol. This also means an interrupted upload resumes instead of
starting over.

## Importing the old archive

The previous system left a `db.json` next to a directory of audio files. Its
entries already carry timestamped chunks, so there is nothing to gain from
putting 62 hours of audio back through the GPU — the text and the timings come
across as they are.

```powershell
docker compose run --rm `
  -v "${PWD}/migrate-stuff:/import:ro" `
  worker python -m worker.import_legacy --source /import --jobs 6
```

| Flag | Default | |
|---|---|---|
| `--limit N` | all | do a couple first as a trial |
| `--jobs N` | 4 | parallel ffmpeg workers |
| `--originals` | `skip` | `copy` also duplicates the source audio into `data/` |
| `--force` | off | re-import entries already present |

What it produces per recording: the **48 kbps Opus proxy** and **waveform
peaks** — the two things the browser needs and the old system never had — plus a
`transcript.json` built from the chunks. Both are ffmpeg-and-numpy work; no
models are loaded, so this runs on CPU while the GPU stays free.

The 16 kHz WAV is written only to compute peaks and deleted immediately: at
~110 MB per hour it would add far more than the audio itself, and no GPU stage
will ever read it. `--originals skip` likewise means the ~12 GB archive is not
duplicated; the UI hides the "download original" button for those jobs.

Job ids are derived from the source UUID, so **the whole import is idempotent** —
re-running updates jobs rather than duplicating them, and an interrupted run can
simply be repeated.

**Imported transcripts have no speaker labels, music markers or summary**, because
the source has no such data. The UI says so on the job page rather than letting
it look like diarization failed.

*Neu verarbeiten* on an imported job produces all three. With `--originals skip`
there is no original left, so the pipeline decodes the **Opus proxy** instead —
worth knowing, though it costs little in practice: every stage works from 16 kHz
mono, and 48 kbps Opus preserves that band well. Import with `--originals copy`
if you would rather reprocess from the untouched source. Reprocessing also
rewrites `transcript.json`, so any manual edits to that job are lost.

## Architecture

```
Browser  ──►  Cloudflare Access  ──►  Tunnel  ──►  127.0.0.1:8080
                                                        │
                                                       api ──── redis
                                                        │         │
                                                     (SQLite)  worker ── ollama
```

- **api** — FastAPI. Serves the SPA, handles uploads, owns the SQLite database,
  streams progress over SSE. It is the *only* writer to the database.
- **worker** — CUDA container running the pipeline. Talks to the API only
  through Redis; writes artifacts to the shared `data/` directory.
- **redis** — job queue (arq) and progress pub/sub.
- **ollama** — optional, summary stage only.

There is no authentication in the application: Cloudflare Access authenticates
at the edge, and the API port is bound to `127.0.0.1` only. **Do not expose port
8080 to the LAN or the internet.**

## The pipeline

Stages run strictly one at a time, each releasing its model before the next
loads. With 8 GB of VRAM this is not an optimisation — Whisper large-v3, the
alignment model, pyannote and the summary LLM cannot coexist.

| # | Stage | Where | What |
|---|-------|-------|------|
| 1 | normalize | CPU | ffmpeg → 16 kHz mono WAV + 48 kbps Opus proxy |
| 2 | peaks | CPU | min/max waveform buckets, gzipped |
| 3 | music | GPU | AST AudioSet tagger → labelled music regions |
| 4 | vad | CPU | Silero speech regions, minus music |
| 5 | asr | GPU | faster-whisper large-v3, int8_float16 |
| 6 | align | GPU | wav2vec2 CTC forced alignment (refinement only) |
| 7 | diarize | GPU | pyannote community-1, masked to the speech regions |
| 8 | merge | CPU | word→speaker assignment, music markers spliced in |
| 9 | summarize | GPU | optional Ollama map-reduce |

Expect roughly **10–15 minutes** for a 90-minute service.

Every stage writes its raw output next to the audio (`music.json`, `vad.json`,
`asr.json`, `diarization.json`), so a late failure can be diagnosed without
re-running the expensive parts. `asr.json` also keeps everything the
hallucination filter *dropped*, with the reason — useful when tuning.

## Tuning

Everything worth changing lives in `worker/worker/config.py`.

### Music detection — tune this on your first real recording

The two thresholds that matter are `MUSIC_THRESHOLD` (absolute confidence) and
`MUSIC_OVER_SPEECH` (how far music must stand up to the speech score). The
defaults are reasoned, not measured on a real Gottesdienst, so plan to adjust
them once.

Every job writes **`data/jobs/<id>/music_windows.json`** with the raw per-window
scores. Find a passage you know is a hymn and read off what the model saw:

```powershell
python -c "import json;[print(w) for w in json.load(open('data/jobs/<id>/music_windows.json')) if 120 < w['start'] < 300]"
```

Then: **music slipping through** (hallucinated text over hymns) → lower
`MUSIC_THRESHOLD`; **speech being swallowed** → raise it, or raise
`MUSIC_OVER_SPEECH`. If short pieces are missed entirely, lower
`MUSIC_MIN_DURATION_S`.

One thing worth knowing before you tune: AudioSet's `Speech` class is very
trigger-happy. In testing it scored 0.796 on a 10-second window containing 0.4
seconds of speech, against 0.774 for `Music` on the organ filling the rest.
That is why `MUSIC_OVER_SPEECH` defaults *below* 1.0 — requiring music to beat
speech outright would suppress genuine hymns, and congregational singing
legitimately excites both classes at once.

### Paragraph length

Whisper emits roughly 30-second segments, which reads as a wall of text and
makes click-to-seek useless. The merge stage cuts them at real sentence ends
using the word timings. Knobs are at the top of
`worker/worker/stages/merge.py`:

- `_MAX_SEGMENT_SECONDS` (18 s) — above this, look for a place to cut
- `_MIN_SPLIT_SECONDS` (6 s) — never make a piece shorter than this
- `_HARD_SPLIT_SECONDS` (30 s) — cut regardless if no punctuation turns up

### Speech lost inside music

If real speech goes missing, check `asr.json` and the merge log for
`inside-music` drops. That rule discards a segment more than
`_MUSIC_OVERLAP_DROP` (50%) inside a detected music region — Whisper narrating a
hymn. It runs *after* forced alignment, on bounds derived from the actual word
timings, and that ordering matters: applied to raw batched-pipeline bounds it
deleted the Vaterunser, because a segment whose span happens to *cover* a hymn
is not the same as a segment *of* a hymn.

### Words alignment cannot place

Forced alignment works from a wav2vec2 character vocabulary that has no digits,
so words made only of them - hymn numbers, Bible verses, years - cannot be
placed. They are kept anyway, timed between their aligned neighbours and marked
`"aligned": false`, because transcript text is rebuilt from the word list and
dropping them turned "Choral Nummer 122 singen" into "Choral Nummer singen".
Their timestamps are approximate; every other word's are not.

**Speakers merged or split**: pin `MAX_SPEAKERS` closer to reality. The defaults
allow 1–12.

**CUDA out of memory**: drop `ASR_BATCH_SIZE` in `.env` from 8 to 4. Watch actual
usage with `nvidia-smi` during a run — peak should stay under ~7.5 GB.

**New hallucination phrases**: add them to `_DENYLIST` in
`worker/worker/hallucinations.py`.

**Do not add an `initial_prompt`** without reading the note in
`worker/worker/config.py`. Priming Whisper with liturgical vocabulary was tried
and removed: over an uncertain passage the model transcribed *the prompt itself*
("Begruessung, Lesung, Predigt, Fuerbitten, ...") with avg_logprob -0.12, i.e.
high confidence, so no threshold caught it. `ASR_INITIAL_PROMPT` exists if you
want to experiment; use a natural sentence, never a word list. The prompt-echo
filter will catch verbatim regurgitation either way.

## Export

The transcript is refined in Word, so the export is built around that: pick
what goes in, decide how it looks, pour it into your own template.

**What goes in.** *Export einrichten…* lists the speakers and the sections of
the service. A section is a run of speech between two pieces of music
(greeting, sermon, announcements …); a legacy import without music markers is
split at pauses longer than two minutes instead. Untick a speaker to drop
everything they say, untick a section to drop that part of the service. The
music that leads into a section is exported with it.

**How it looks.** Speaker names, timestamps, music markers, title and summary
are each a switch. *Absätze* decides where paragraphs break (at every speaker
change, short blocks, every sentence, or one paragraph per section) and
*Zwischen den Abschnitten* what separates two sections (nothing, a blank line,
a heading, a page break). These settings are stored in the browser's local
storage; *Sofort herunterladen* reuses them for the whole recording without
opening the dialog. The defaults are tuned for editing: no labels, no
timestamps, a new paragraph at every speaker change.

**Word templates.** Upload any `.docx` under *Vorlagen verwalten* and write
placeholders wherever the recording's data should land. Everything else in the
document — styles, headers, logos, tables — stays as it is. Placeholders are
case-insensitive and may sit inside a heading, a table cell, a header or a
footer:

| Placeholder            | Becomes                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `{{Titel}}`            | title of the recording                                             |
| `{{Datum}}`            | service date as `18.08.2023`                                       |
| `{{Dauer}}`            | length of the recording                                            |
| `{{Sprecher}}`         | names of the exported speakers, comma-separated                    |
| `{{Lieder}}`           | announced hymn numbers, comma-separated                            |
| `{{Liederliste}}`      | one paragraph per hymn; a bulleted placeholder gives a bulleted list |
| `{{Zusammenfassung}}`  | the summary, paragraph by paragraph                                |
| `{{Text}}`             | the transcript, laid out as configured                             |

The paragraph holding `{{Text}}` (or `{{Liederliste}}`, `{{Zusammenfassung}}`)
lends its style to every paragraph the export generates in its place, so the
template decides font, spacing and indentation. Unknown placeholders are left
untouched and flagged in the template list. Templates live in
`data/templates/`, one file per row in the `templates` table. The preview in
the dialog renders the finished `.docx` in the browser, template included.

The old `GET /api/jobs/<id>/export/<fmt>` still produces the fixed
everything-included layout; the dialog uses `POST` with an options body
(see `ExportOptions` in `api/app/exports.py`).

## Development

```powershell
docker compose up -d redis api worker   # backend on :8080
cd web; npm run dev                     # frontend on :5173, proxies to :8080
```

## Data layout

```
data/
  transcribe.db              SQLite (jobs, uploads, templates)
  templates/<id>.docx        Word templates for the export
  uploads/*.part          in-flight chunked uploads
  jobs/<id>/
    original.<ext>        what was uploaded
    audio.wav             16 kHz mono pipeline audio
    audio.opus            48 kbps playback proxy
    peaks.json[.gz]       waveform
    music.json            detected music regions
    music_windows.json    per-window music/speech scores (for tuning)
    vad.json              speech regions
    asr.json              raw ASR output + dropped segments
    diarization.json      speaker turns
    transcript.json       the editable document (source of truth)
    summary.json          optional summary
```

## What has actually been verified

Measured on real recordings from the archive, not on synthetic fixtures.

### Against the previous system, same audio

A 58-minute service (2026-08-30) reprocessed and compared with what the old
system produced for the identical recording:

| | old | new |
|---|---|---|
| Hallucinated segments | **54** | **0** |
| Speakers | none | 3 |
| Music labelled | none | 9 regions |
| Words | 2454 | 2066 |

The old transcript opened with `Untertitelung des ZDF, 2020` repeated over the
organ prelude. The new one opens with the first actual words, at 6:48, where the
music stops.

Across the whole imported archive, **67 of 121 transcripts (55%) contain
hallucinations — 539 segments**. That is the failure this project exists to
prevent, counted rather than assumed.

### Music detection, checked in both directions

Not just "did it find music" but "did it eat speech". For each detected region,
what the old system transcribed there:

- `47.0–57.1 min [Orgelspiel]` — old system: 41 segments, **40 of them junk**.
  Correctly silenced.
- `0.0–6.8 min [Musik]` — 12 of 13 junk. Correct.
- `9.5–13.2 min [Gemeindegesang]` — 90 words of *"Alleluia, Alleluia…"*. Real
  hymn lyrics, labelled rather than transcribed. That is the intended trade.

Two services with very different shapes, which is the useful part: 57% of
windows tagged as music in one, **26% in the other** (41.4 minutes of speech in
72.7). The detector is not blanket-tagging.

### Everything else

GPU passthrough and all nine stages; resumable upload including stale-PATCH
retry and format rejection; forced alignment; all five exports; editing, speaker
renaming, SSE progress; the legacy import converging on re-run; 66 unit tests
(`.\scriptserify.ps1`).

**Timing, measured:** ~13 minutes for a 58-minute service, ~9 minutes when the
summary is skipped. Peak VRAM stayed comfortable throughout (7.4 GB free of
8.6 GB) — including diarization of a 72-minute recording, which was the memory
risk worth watching.

### The one place real speech is still lost

Short spoken announcements immediately beside music get absorbed into the music
region — *"Wir singen die Strophen 1 bis 4 und 6."* sits inside a `[Musik]` span
and does not survive. This is a resolution limit: a three-second announcement
inside a ten-second classification window does not change that window's verdict.
Halving `MUSIC_HOP_S` (5 → 2.5) doubles boundary resolution for roughly a minute
more per job, if that trade is worth it to you.

## Open issue: words clipped at music/speech boundaries

Full write-up, including what has already been tried and why each attempt failed:
[`docs/handoff-music-speech-boundaries.md`](docs/handoff-music-speech-boundaries.md).

A few words are lost where speech meets music. Most visible on job
`7cfcf258151a411da7edd6d852fd19dc` (a 73-minute service from 2026-08-27), where
it happens at essentially every boundary.

Measured against that recording's previous transcript, after the redistribution
fix: 26 words, 0.4% of the text, in four short fragments cut mid-phrase, each
the head or tail of a sentence.

Reproduce the measurement by diffing a reprocessed transcript against the
recording's pre-pipeline text, classifying each old-only run as looping, inside
music, or unexplained — the unexplained bucket is this issue.

Four places decide a boundary, and the fault is likely shared between them:

- `VAD_SPEECH_PAD_MS` (200 ms) in `worker/worker/config.py` pads each speech
  region. A word starting just before the pad is outside the region.
- `clip_to_speech` in `worker/worker/stages/merge.py` truncates a segment at the
  end of the speech run it starts in.
- `split_across_speech` distributes a merged segment's words across the runs it
  spans **in proportion to each run's duration**. That is a heuristic, and it is
  weakest exactly at the joins — the most likely culprit for mid-phrase cuts.
- `_music_without_speech` clips music regions off transcribed speech, which
  moves the visible boundary but not the word list.

`data/jobs/<id>/vad.json`, `music.json` and `asr.json` are all kept, so the
boundary can be inspected without re-running the GPU stages. Note that
`asr.json` holds the bounds *after* tightening, and the word timings inside a
merged segment are themselves unreliable — that is what made the naive fixes
fail.

## Known limits

- **Laptop sleep suspends a running job.** If it wakes, the worker carries on.
  If the worker died, the API notices within 60 seconds: the worker refreshes a
  Redis heartbeat while it works, and the API marks a job failed once that
  heartbeat is gone, so the UI offers a retry rather than spinning forever.
- **Retries reuse the normalised audio** but re-run every GPU stage, which
  rewrites `transcript.json` — so a retry **discards manual edits and speaker
  names**. The UI only offers retry on jobs that failed (which have no
  transcript yet), but the API endpoint will do it to any job.
- **One job at a time**, by design.
