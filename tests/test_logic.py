"""Tests for the pure logic - no GPU, no models, no containers.

These cover the parts most likely to be quietly wrong: the German hallucination
filter, region arithmetic, and the word-to-speaker assignment that decides who
said what.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "api"))

from worker import hallucinations  # noqa: E402
from worker.stages import merge, vad  # noqa: E402


# ---------------------------------------------------------------------------
# Hallucination filter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Untertitelung des ZDF für funk, 2017",
    "Untertitel im Auftrag des ZDF für funk, 2017",
    "Untertitel von Stephanie Geiges",
    "Untertitelung aufgrund der Amara.org-Community",
    "Vielen Dank fürs Zuschauen!",
    "Vielen Dank für's Zuschauen.",
    "Copyright WDR 2020",
    "Bis zum nächsten Mal!",
    "Abonniert den Kanal",
    "Musik",
    "* Musik *",
])
def test_known_artifacts_are_dropped(text: str) -> None:
    assert hallucinations.is_denylisted(text)


@pytest.mark.parametrize("text", [
    "Im Namen des Vaters und des Sohnes und des Heiligen Geistes.",
    "Wir hören eine Lesung aus dem Evangelium nach Matthäus.",
    "Vielen Dank an alle, die den Gottesdienst vorbereitet haben.",
    "Der Herr segne dich und behüte dich.",
    "Lasst uns beten für die Menschen in Not.",
])
def test_real_liturgy_survives(text: str) -> None:
    assert not hallucinations.is_denylisted(text)


def test_repetition_runs_collapse() -> None:
    looped = "und dann " * 8
    assert hallucinations.collapse_repetitions(looped.strip()) == "und dann"


def test_normal_repetition_is_preserved() -> None:
    # Saying something twice for emphasis is ordinary speech.
    text = "Halleluja Halleluja wir singen"
    assert hallucinations.collapse_repetitions(text) == text


def test_loop_detection() -> None:
    assert hallucinations.looks_like_loop("ja ja ja ja ja ja ja ja ja ja")
    assert not hallucinations.looks_like_loop(
        "Der Predigttext steht im Brief des Paulus an die Gemeinde in Rom."
    )


def test_clean_splits_kept_and_dropped() -> None:
    segments = [
        {"text": "Guten Morgen, liebe Gemeinde.", "avg_logprob": -0.3},
        {"text": "Untertitelung des ZDF für funk, 2017", "avg_logprob": -0.4},
        {"text": "Wir beginnen im Namen des Vaters.", "avg_logprob": -0.2},
        {"text": "kaum verständlich", "avg_logprob": -2.5},
    ]
    kept, dropped = hallucinations.clean(segments)
    assert [s["text"] for s in kept] == [
        "Guten Morgen, liebe Gemeinde.",
        "Wir beginnen im Namen des Vaters.",
    ]
    assert {s["drop_reason"] for s in dropped} == {"denylist", "low-confidence"}


# ---------------------------------------------------------------------------
# Region arithmetic
# ---------------------------------------------------------------------------
def test_subtract_splits_a_region_in_two() -> None:
    speech = [{"start": 0.0, "end": 100.0}]
    music = [{"start": 40.0, "end": 60.0}]
    assert vad.subtract(speech, music) == [
        {"start": 0.0, "end": 40.0},
        {"start": 60.0, "end": 100.0},
    ]


def test_subtract_removes_a_fully_covered_region() -> None:
    assert vad.subtract([{"start": 10.0, "end": 20.0}],
                        [{"start": 0.0, "end": 30.0}]) == []


def test_subtract_trims_an_overlapping_edge() -> None:
    assert vad.subtract([{"start": 0.0, "end": 30.0}],
                        [{"start": 20.0, "end": 40.0}]) == [{"start": 0.0, "end": 20.0}]


def test_merge_overlapping_joins_touching_regions() -> None:
    merged = vad.merge_overlapping([
        {"start": 0.0, "end": 10.0},
        {"start": 8.0, "end": 15.0},
        {"start": 20.0, "end": 25.0},
    ])
    assert merged == [{"start": 0.0, "end": 15.0}, {"start": 20.0, "end": 25.0}]


def test_covered_fraction() -> None:
    regions = [{"start": 0.0, "end": 5.0}]
    assert vad.covered_fraction(0.0, 10.0, regions) == pytest.approx(0.5)
    assert vad.covered_fraction(6.0, 10.0, regions) == 0.0


# ---------------------------------------------------------------------------
# Speaker assignment
# ---------------------------------------------------------------------------
def _words(pairs: list[tuple[str, float, float]]) -> list[dict]:
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


def test_speaker_index_point_lookup() -> None:
    index = merge.SpeakerIndex([
        {"start": 0.0, "end": 10.0, "speaker": "SPEAKER_00"},
        {"start": 10.0, "end": 20.0, "speaker": "SPEAKER_01"},
    ])
    assert index.at(5.0) == "SPEAKER_00"
    assert index.at(15.0) == "SPEAKER_01"
    # Just outside any turn, but close enough to snap.
    assert index.at(20.3) == "SPEAKER_01"
    # Far outside.
    assert index.at(90.0) is None


def test_segment_splits_at_a_speaker_change() -> None:
    """The point of forced alignment: Whisper picks segment boundaries from
    prosody and happily runs a segment straight through a speaker change."""
    index = merge.SpeakerIndex([
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00"},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01"},
    ])
    segment = {
        "start": 0.0,
        "end": 6.0,
        "text": "Der Herr sei mit euch und mit deinem Geiste",
        "words": _words([
            ("Der", 0.1, 0.4), ("Herr", 0.5, 0.9), ("sei", 1.0, 1.3),
            ("mit", 1.4, 1.7), ("euch", 1.8, 2.4),
            ("und", 3.2, 3.5), ("mit", 3.6, 3.9), ("deinem", 4.0, 4.6),
            ("Geiste", 4.7, 5.4),
        ]),
    }
    pieces = merge._split_by_speaker(segment, index)
    assert len(pieces) == 2
    assert pieces[0]["speaker"] == "SPEAKER_00"
    assert pieces[0]["text"] == "Der Herr sei mit euch"
    assert pieces[1]["speaker"] == "SPEAKER_01"
    assert pieces[1]["text"] == "und mit deinem Geiste"
    # Outer bounds are preserved so the timeline has no holes.
    assert pieces[0]["start"] == 0.0
    assert pieces[1]["end"] == 6.0


def test_single_stray_word_does_not_create_a_turn() -> None:
    """A one-word diarization wobble should be absorbed, not promoted."""
    index = merge.SpeakerIndex([
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
        {"start": 2.0, "end": 2.3, "speaker": "SPEAKER_01"},
        {"start": 2.3, "end": 6.0, "speaker": "SPEAKER_00"},
    ])
    segment = {
        "start": 0.0,
        "end": 6.0,
        "text": "Wir hören jetzt auf das Wort",
        "words": _words([
            ("Wir", 0.2, 0.6), ("hören", 0.7, 1.2), ("jetzt", 1.3, 1.9),
            ("auf", 2.05, 2.2),
            ("das", 2.5, 2.8), ("Wort", 2.9, 3.4),
        ]),
    }
    pieces = merge._split_by_speaker(segment, index)
    assert len(pieces) == 1
    assert pieces[0]["speaker"] == "SPEAKER_00"
    assert pieces[0]["text"] == "Wir hören jetzt auf das Wort"


def test_music_regions_are_interleaved_by_time() -> None:
    document = merge.run(
        job_id="j1",
        duration=100.0,
        language="de",
        asr_segments=[
            {"start": 0.0, "end": 10.0, "text": "Begrüßung", "words": None},
            {"start": 70.0, "end": 80.0, "text": "Predigt", "words": None},
        ],
        turns=[{"start": 0.0, "end": 90.0, "speaker": "SPEAKER_00"}],
        music_regions=[{"start": 20.0, "end": 60.0, "marker": "[Gemeindegesang]"}],
    )
    kinds = [(s["type"], s["text"]) for s in document["segments"]]
    assert kinds == [
        ("speech", "Begrüßung"),
        ("music", "[Gemeindegesang]"),
        ("speech", "Predigt"),
    ]
    assert document["segments"][0]["id"] == "s0"
    assert document["speakers"]["SPEAKER_00"]["label"] == "Sprecher 1"


# ---------------------------------------------------------------------------
# Export formatting
# ---------------------------------------------------------------------------
def test_subtitle_clock_formats() -> None:
    from app import exports

    assert exports.clock(0) == "00:00:00,000"
    assert exports.clock(3725.5) == "01:02:05,500"
    assert exports.clock(3725.5, millis_sep=".") == "01:02:05.500"
    # Rounding must not produce ",1000".
    assert exports.clock(1.9999) == "00:00:02,000"


def test_short_clock() -> None:
    from app import exports

    assert exports.short_clock(65) == "1:05"
    assert exports.short_clock(3725) == "1:02:05"


def test_grouped_merges_consecutive_same_speaker() -> None:
    from app import exports

    doc = {
        "speakers": {"SPEAKER_00": {"label": "Pfarrerin"}},
        "segments": [
            {"type": "speech", "speaker": "SPEAKER_00", "start": 0, "end": 3, "text": "Guten Morgen."},
            {"type": "speech", "speaker": "SPEAKER_00", "start": 3, "end": 6, "text": "Schön, dass Sie da sind."},
            {"type": "music", "marker": "[Orgelspiel]", "start": 6, "end": 60, "text": "[Orgelspiel]"},
            {"type": "speech", "speaker": "SPEAKER_00", "start": 60, "end": 65, "text": "Wir beten."},
        ],
    }
    blocks = list(exports.grouped(doc))
    assert len(blocks) == 3
    assert blocks[0]["text"] == "Guten Morgen. Schön, dass Sie da sind."
    assert blocks[1]["type"] == "music"
    assert blocks[2]["text"] == "Wir beten."


# ---------------------------------------------------------------------------
# Waveform peaks
# ---------------------------------------------------------------------------
def test_peaks_are_generated_and_normalized(tmp_path) -> None:
    """Peaks must come out as int8 min/max pairs, normalised to the full range.

    This is what lets the browser skip decoding entirely, so getting the shape
    wrong breaks the player on exactly the machine it was designed for.
    """
    import json
    import math
    import wave as wave_module

    from worker.stages import peaks as peaks_stage

    rate = 16_000
    seconds = 3
    path = tmp_path / "audio.wav"
    with wave_module.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for i in range(rate * seconds):
            value = int(20000 * math.sin(2 * math.pi * 440 * i / rate))
            frames += int(value).to_bytes(2, "little", signed=True)
        handle.writeframes(bytes(frames))

    peaks_stage.run(path, tmp_path, float(seconds))
    payload = json.loads((tmp_path / "peaks.json").read_text())

    assert payload["pixels_per_second"] == peaks_stage.PEAKS_PER_SECOND
    assert payload["duration"] == 3.0
    # Two values (min, max) per bucket.
    expected_buckets = rate * seconds // (rate // peaks_stage.PEAKS_PER_SECOND)
    assert len(payload["data"]) == expected_buckets * 2
    assert all(-127 <= value <= 127 for value in payload["data"])
    # Normalised, so the loudest bucket reaches the top of the range.
    assert max(abs(value) for value in payload["data"]) == 127
    # Alternating min/max: even indices negative, odd positive for a sine.
    assert payload["data"][0] < 0 < payload["data"][1]
    # The gzipped twin the API prefers must exist and be much smaller.
    assert (tmp_path / "peaks.json.gz").stat().st_size < (tmp_path / "peaks.json").stat().st_size


# ---------------------------------------------------------------------------
# Music region assembly
# ---------------------------------------------------------------------------
def _window(start: float, end: float, marker: str | None, score: float,
            is_music: bool) -> dict:
    return {"start": start, "end": end, "marker": marker, "music": score,
            "speech": 0.0, "is_music": is_music}


def test_music_windows_merge_into_one_region() -> None:
    from worker.stages.music import _to_regions

    # Contiguous 5 s core spans, as the centre-attribution produces.
    windows = [_window(t, t + 5, "[Orgelspiel]", 0.9, True) for t in range(0, 40, 5)]
    regions = _to_regions(windows)
    assert len(regions) == 1
    assert regions[0]["start"] == 0.0
    assert regions[0]["end"] == 40.0
    assert regions[0]["marker"] == "[Orgelspiel]"


def test_short_music_blip_is_discarded() -> None:
    from worker.stages.music import _to_regions

    # A single 5 s window is below MUSIC_MIN_DURATION_S and must not become a
    # region - otherwise a chord under speech fragments the transcript.
    assert _to_regions([_window(10, 15, "[Musik]", 0.8, True)]) == []


def test_region_marker_is_the_dominant_family() -> None:
    from worker.stages.music import _to_regions

    # A hymn that opens with organ then becomes singing should read as singing.
    windows = [
        _window(0, 5, "[Orgelspiel]", 0.6, True),
        _window(5, 10, "[Gemeindegesang]", 0.9, True),
        _window(10, 15, "[Gemeindegesang]", 0.92, True),
        _window(15, 20, "[Gemeindegesang]", 0.88, True),
    ]
    regions = _to_regions(windows)
    assert len(regions) == 1
    assert regions[0]["marker"] == "[Gemeindegesang]"


def test_speech_between_two_hymns_splits_the_regions() -> None:
    from worker.stages.music import _to_regions

    windows = (
        [_window(t, t + 5, "[Gemeindegesang]", 0.9, True) for t in range(0, 20, 5)]
        + [_window(t, t + 5, None, 0.1, False) for t in range(20, 60, 5)]
        + [_window(t, t + 5, "[Orgelspiel]", 0.85, True) for t in range(60, 80, 5)]
    )
    regions = _to_regions(windows)
    assert len(regions) == 2
    assert regions[0]["end"] == 20.0
    assert regions[1]["start"] == 60.0


# ---------------------------------------------------------------------------
# Prompt echo
# ---------------------------------------------------------------------------
PROMPT = ("Aufnahme eines evangelischen Gottesdienstes. Begruessung, Lesung, Predigt, "
          "Fuerbitten, Vaterunser, Abendmahl, Kollekte, Segen, Halleluja, Amen.")


def test_prompt_echo_is_detected() -> None:
    """Regression: Whisper emitted the initial prompt verbatim as a transcript,
    with avg_logprob -0.12, so no confidence threshold caught it."""
    echoed = ("Begruessung, Lesung, Predigt, Fuerbitten, Vaterunser, Abendmahl, "
              "Kollekte, Segen, Halleluja, Amen.")
    assert hallucinations.is_prompt_echo(echoed, PROMPT)


def test_prompt_echo_does_not_eat_real_speech() -> None:
    # Uses several words that appear in the prompt, but is genuine speech.
    real = ("Nach der Lesung folgt die Predigt, und danach singen wir gemeinsam "
            "das Lied Nummer dreihundertzwoelf aus dem Gesangbuch.")
    assert not hallucinations.is_prompt_echo(real, PROMPT)
    assert not hallucinations.is_prompt_echo("Wir beten das Vaterunser.", PROMPT)


def test_prompt_echo_is_inert_without_a_prompt() -> None:
    assert not hallucinations.is_prompt_echo("Lesung Predigt Segen Amen", None)


def test_clean_reports_prompt_echo_and_keeps_confidence() -> None:
    segments = [
        {"text": "Guten Morgen, liebe Gemeinde.", "avg_logprob": -0.3},
        # High confidence - only the prompt check can catch this one.
        {"text": "Begruessung, Lesung, Predigt, Fuerbitten, Vaterunser, Abendmahl, "
                 "Kollekte, Segen, Halleluja, Amen.", "avg_logprob": -0.12},
    ]
    kept, dropped = hallucinations.clean(segments, prompt=PROMPT)
    assert len(kept) == 1
    assert dropped[0]["drop_reason"] == "prompt-echo"


# ---------------------------------------------------------------------------
# Music / speech overlap
# ---------------------------------------------------------------------------
def test_music_region_is_clipped_off_overlapping_speech() -> None:
    """Regression: a 10 s classification window scores as music even when it is
    only ~40% music, so regions ran several seconds into the following speech
    and the transcript showed [Orgelspiel] overlapping a sentence."""
    document = merge.run(
        job_id="j", duration=80.0, language="de",
        asr_segments=[
            {"start": 9.69, "end": 22.0, "text": "Herzlich willkommen.", "words": None},
        ],
        turns=[{"start": 9.0, "end": 22.0, "speaker": "SPEAKER_00"}],
        music_regions=[{"start": 0.0, "end": 12.5, "marker": "[Orgelspiel]"}],
    )
    music = [s for s in document["segments"] if s["type"] == "music"]
    speech = [s for s in document["segments"] if s["type"] == "speech"]
    assert len(music) == 1
    # Clipped back to where the speech starts, not left overlapping it.
    assert music[0]["end"] == 9.69
    assert music[0]["start"] == 0.0
    assert speech[0]["start"] == 9.69
    # And the timeline is strictly ordered with no overlap anywhere.
    ordered = document["segments"]
    assert all(ordered[i]["end"] <= ordered[i + 1]["start"] + 1e-6
               for i in range(len(ordered) - 1))


def test_music_is_trimmed_where_it_overruns_into_speech() -> None:
    """The realistic case: the region's tail overlaps the start of the next
    passage of speech. A segment sitting *wholly* inside music is treated as
    hymn narration and dropped instead - see the test below."""
    document = merge.run(
        job_id="j", duration=120.0, language="de",
        asr_segments=[{"start": 55.0, "end": 95.0, "text": "Liebe Gemeinde.",
                       "words": None}],
        turns=[{"start": 55.0, "end": 95.0, "speaker": "SPEAKER_00"}],
        music_regions=[{"start": 20.0, "end": 60.0, "marker": "[Gemeindegesang]"}],
    )
    music = [(s["start"], s["end"]) for s in document["segments"] if s["type"] == "music"]
    # Clipped back off the speech rather than left overlapping it.
    assert music == [(20.0, 55.0)]
    ordered = document["segments"]
    assert all(ordered[i]["end"] <= ordered[i + 1]["start"] + 1e-6
               for i in range(len(ordered) - 1))


def test_music_reduced_to_a_sliver_is_dropped() -> None:
    document = merge.run(
        job_id="j", duration=80.0, language="de",
        # Mostly outside the music, so it survives the inside-music check, but
        # its start clips the region down to 2 s - below the floor, so it goes.
        asr_segments=[{"start": 11.0, "end": 60.0, "text": "Lange Rede.",
                       "words": None}],
        turns=[{"start": 11.0, "end": 60.0, "speaker": "SPEAKER_00"}],
        music_regions=[{"start": 9.0, "end": 30.0, "marker": "[Musik]"}],
    )
    assert [s for s in document["segments"] if s["type"] == "music"] == []


# ---------------------------------------------------------------------------
# Segment bounds, music overlap, sentence splitting
# ---------------------------------------------------------------------------
def test_bounds_are_tightened_to_the_words() -> None:
    """Regression from a real 58-minute service: faster-whisper's batched
    pipeline merges VAD chunks across musical gaps, so a segment claimed to span
    535s-1067s while its text was one sentence spoken at the start."""
    segment = {
        "start": 535.8, "end": 1066.9,
        "text": "Fuehre uns nicht in Versuchung.",
        "words": _words([("Fuehre", 536.0, 536.4), ("uns", 536.5, 536.7),
                         ("nicht", 536.8, 537.1), ("in", 537.2, 537.3),
                         ("Versuchung.", 537.4, 538.2)]),
    }
    tightened = merge.tighten_bounds(segment)
    assert tightened["start"] == 536.0
    assert tightened["end"] == 538.2
    assert tightened["text"] == segment["text"]


def test_tighten_is_a_noop_without_words() -> None:
    segment = {"start": 10.0, "end": 20.0, "text": "x", "words": None}
    assert merge.tighten_bounds(segment) == segment


def test_confident_speech_over_music_is_kept_after_tightening() -> None:
    """The Vaterunser was being deleted: spoken during a passage the tagger
    called music, inside a segment whose bogus bounds covered the whole hymn."""
    music = [{"start": 540.0, "end": 1060.0, "marker": "[Gemeindegesang]"}]
    spoken = {"start": 536.0, "end": 538.2, "text": "Fuehre uns nicht in Versuchung."}
    kept, dropped = merge._drop_inside_music([spoken], music)
    assert kept == [spoken]
    assert dropped == []


def test_narration_genuinely_inside_music_is_dropped() -> None:
    music = [{"start": 100.0, "end": 200.0, "marker": "[Orgelspiel]"}]
    inside = {"start": 120.0, "end": 160.0, "text": "Halleluja halleluja"}
    kept, dropped = merge._drop_inside_music([inside], music)
    assert kept == []
    assert dropped[0]["drop_reason"] == "inside-music"


def test_long_segment_splits_on_sentence_ends() -> None:
    words = _words([
        ("Zum", 0.0, 0.4), ("Kirchentag", 0.5, 1.2), ("gehen", 1.3, 1.7),
        ("wir.", 1.8, 8.0),
        ("Wir", 8.5, 8.9), ("beten", 9.0, 9.5), ("gemeinsam.", 9.6, 16.0),
        ("Amen", 16.5, 17.0), ("und", 17.1, 17.4), ("dann", 17.5, 24.0),
    ])
    segment = {"start": 0.0, "end": 24.0,
               "text": "Zum Kirchentag gehen wir. Wir beten gemeinsam. Amen und dann",
               "words": words}
    pieces = merge._split_long(segment)
    assert len(pieces) >= 2
    assert pieces[0]["text"] == "Zum Kirchentag gehen wir."
    # Outer edges preserved, so the timeline has no holes.
    assert pieces[0]["start"] == 0.0
    assert pieces[-1]["end"] == 24.0
    assert all(p["end"] > p["start"] for p in pieces)


def test_short_segment_is_left_alone() -> None:
    segment = {"start": 0.0, "end": 5.0, "text": "Guten Morgen.",
               "words": _words([("Guten", 0.0, 0.5), ("Morgen.", 0.6, 1.2)])}
    assert merge._split_long(segment) == [segment]


def test_split_falls_back_to_a_hard_cut_without_punctuation() -> None:
    words = _words([(f"wort{i}", i * 4.0, i * 4.0 + 3.5) for i in range(12)])
    segment = {"start": 0.0, "end": 48.0,
               "text": " ".join(w["word"] for w in words), "words": words}
    pieces = merge._split_long(segment)
    assert len(pieces) > 1
    assert all(p["end"] - p["start"] <= 35.0 for p in pieces)
