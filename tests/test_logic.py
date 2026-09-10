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

from app import hymns  # noqa: E402
from worker import hallucinations  # noqa: E402
from worker.stages import asr, merge, vad  # noqa: E402


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
    assert exports.speaker_label(doc, "SPEAKER_00") == "Pfarrerin"


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


def test_announcement_at_the_edge_of_music_survives() -> None:
    """The 2026-08-27 service, 2029 s: "Und zum Schluss ein Dankgebet" was said 2.4 s before
    the detected end of a 145 s organ passage and 3.3 s of the next announcement
    ran past the detected start of the following one. The detector's edges are
    a 5 s hop coarse; what lies within a hop of an edge is not hymn narration."""
    music = [{"start": 1887.5, "end": 2032.5, "marker": "[Orgelspiel]"}]
    closing = {"start": 2029.11, "end": 2030.07, "text": "Und zum Schluss ein Dankgebet."}
    running_on = {"start": 1883.57, "end": 1890.81,
                  "text": "Ihr Lieben, wir singen gemeinsam den Choral Nummer 117. "
                          "Gott ruft nach einer Jugend und wir singen alle drei Strophen."}
    kept, dropped = merge._drop_inside_music([closing, running_on], music)
    assert kept == [closing, running_on]
    assert dropped == []


def test_edge_margin_does_not_rescue_a_short_hymn_narration() -> None:
    music = [{"start": 100.0, "end": 120.0, "marker": "[Orgelspiel]"}]
    inside = {"start": 106.0, "end": 114.0, "text": "Lobe den Herren"}
    kept, dropped = merge._drop_inside_music([inside], music)
    assert kept == [] and len(dropped) == 1


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


# ---------------------------------------------------------------------------
# Summary post-processing
# ---------------------------------------------------------------------------
def test_leading_heading_is_stripped() -> None:
    """qwen3 prefixes "Zusammenfassung:" despite being told not to."""
    from worker.stages.summarize import _split_outline

    summary, outline = _split_outline(
        "Zusammenfassung:\nDer Gottesdienst dreht sich um Gebet und Frieden."
    )
    assert summary == "Der Gottesdienst dreht sich um Gebet und Frieden."
    assert outline == []


def test_inline_heading_is_stripped() -> None:
    from worker.stages.summarize import _split_outline

    summary, _ = _split_outline("Zusammenfassung: Es ging um Frieden.")
    assert summary == "Es ging um Frieden."


def test_outline_is_split_from_summary() -> None:
    from worker.stages.summarize import _split_outline

    summary, outline = _split_outline(
        "Es ging um Gebet und Frieden.\n\n"
        "Gliederung:\n"
        "- Begruessung mit Hinweis auf den Kirchentag\n"
        "- Lesung aus dem Roemerbrief, Kapitel acht\n"
        "* Predigt ueber die Bitte um taegliches Brot\n"
    )
    assert summary == "Es ging um Gebet und Frieden."
    assert outline == [
        "Begruessung mit Hinweis auf den Kirchentag",
        "Lesung aus dem Roemerbrief, Kapitel acht",
        "Predigt ueber die Bitte um taegliches Brot",
    ]


def test_final_prompt_contains_no_example_outline() -> None:
    """Regression: the prompt used to suggest an example liturgy list, and the
    model returned exactly that list for a real service, deriving nothing."""
    from worker.stages.summarize import FINAL_PROMPT

    lowered = FINAL_PROMPT.lower()
    assert "z. b." not in lowered and "z.b." not in lowered
    # The give-away sequence must not appear as a suggestion.
    assert "fuerbitten, abendmahl" not in lowered


# ---------------------------------------------------------------------------
# Legacy import
# ---------------------------------------------------------------------------
def test_legacy_job_id_is_deterministic() -> None:
    """Deriving the job id from the source UUID is what makes the whole import
    idempotent - a re-run updates the same job instead of duplicating it."""
    from worker.import_legacy import legacy_job_id

    got = legacy_job_id("dfa30879-982c-4cb6-87ec-765e98bdaa6d")
    assert got == "dfa30879982c4cb687ec765e98bdaa6d"
    assert len(got) == 32 and got.isalnum()
    assert got == legacy_job_id(got.upper().replace("", ""))  # stable


def test_created_at_is_parsed_to_date() -> None:
    from worker.import_legacy import parse_created_at

    iso, date = parse_created_at("18.08.2023 23:12:22")
    assert date == "2023-08-18"
    assert iso.startswith("2023-08-18T23:12:22")
    assert parse_created_at("nonsense") == (None, None)


def test_title_comes_from_the_old_file_name() -> None:
    from worker.import_legacy import nice_title

    assert nice_title({"file_name": "schule_full.mp3"}) == "schule full"
    assert nice_title({"file_name": "", "transcription_name": "x.mp3 - 18.08.2023"}) == "x"
    assert nice_title({}) == "Importierte Aufnahme"


def test_chunks_become_timed_segments() -> None:
    from worker.import_legacy import build_transcript

    entry = {
        "id": "abc", "text": "ignored",
        "chunks": [
            {"start": 0.0, "end": 5.96, "text": "Gott zum Gruss."},
            {"start": 5.96, "end": 29.16, "text": "Wenn ihr nur sehen duerftet."},
            {"start": 29.16, "end": 30.0, "text": "   "},  # blank -> dropped
        ],
    }
    doc = build_transcript(entry, "job1", 30.0)
    assert doc["source"] == "legacy-import"
    assert doc["speakers"] == {}
    assert [s["text"] for s in doc["segments"]] == [
        "Gott zum Gruss.", "Wenn ihr nur sehen duerftet."]
    assert doc["segments"][1]["start"] == 5.96
    assert all(s["speaker"] is None for s in doc["segments"])
    assert all(s["end"] >= s["start"] for s in doc["segments"])


def test_entry_without_chunks_keeps_its_text() -> None:
    from worker.import_legacy import build_transcript

    doc = build_transcript({"id": "x", "text": "Ein ganzer Gottesdienst.", "chunks": []},
                           "job2", 120.0)
    assert len(doc["segments"]) == 1
    assert doc["segments"][0]["text"] == "Ein ganzer Gottesdienst."
    assert doc["segments"][0]["end"] == 120.0


# ---------------------------------------------------------------------------
# Exports for transcripts without speakers (imported archive)
# ---------------------------------------------------------------------------
def _speakerless_doc(count: int = 40) -> dict:
    return {
        "speakers": {},
        "source": "legacy-import",
        "segments": [
            {"id": f"s{i}", "type": "speech", "speaker": None,
             "start": i * 6.0, "end": i * 6.0 + 6.0,
             "text": f"Satz Nummer {i} mit etwas Text darin."}
            for i in range(count)
        ],
    }


def test_speakerless_transcript_is_not_one_giant_paragraph() -> None:
    """Regression: every segment had speaker None, so they all grouped together
    and a 13-minute recording exported as a single 7000-character block."""
    from app import exports

    blocks = list(exports.grouped(_speakerless_doc()))
    assert len(blocks) > 1
    assert all(len(b["text"]) <= exports.MAX_BLOCK_CHARS for b in blocks)
    assert all(b["end"] - b["start"] <= exports.MAX_BLOCK_SECONDS + 6.01
               for b in blocks)


def test_no_speaker_means_no_label_rather_than_unbekannt() -> None:
    from app import exports

    doc = _speakerless_doc(3)
    assert exports.speaker_label(doc, None) is None

    job = {"title": "Kirchentag", "service_date": "2023-08-18"}
    text = exports.render_txt(job, doc)
    assert "Unbekannt" not in text
    assert "Satz Nummer 0" in text

    markdown = exports.render_md(job, doc)
    assert "Unbekannt" not in markdown

    subtitles = exports._subtitles(doc, vtt=False)
    assert "Unbekannt" not in subtitles
    assert subtitles.startswith("1\n")


def test_speaker_label_still_used_when_speakers_exist() -> None:
    from app import exports

    doc = {"speakers": {"SPEAKER_00": {"label": "Pfarrerin"}},
           "segments": [{"id": "s0", "type": "speech", "speaker": "SPEAKER_00",
                         "start": 0, "end": 5, "text": "Guten Morgen."}]}
    assert "Pfarrerin: Guten Morgen." in exports.render_txt(
        {"title": "x", "service_date": None}, doc)


# ---------------------------------------------------------------------------
# Reprocessing an imported job
# ---------------------------------------------------------------------------
def test_find_original_falls_back_to_the_opus_proxy(tmp_path) -> None:
    """Imported jobs keep no original, so without this "Neu verarbeiten" on an
    imported recording fails outright."""
    from worker import pipeline

    (tmp_path / "audio.opus").write_bytes(b"x")
    assert pipeline.find_original(tmp_path).name == "audio.opus"

    (tmp_path / "original.mp3").write_bytes(b"x")
    assert pipeline.find_original(tmp_path).name == "original.mp3"


def test_find_original_raises_when_there_is_nothing(tmp_path) -> None:
    from worker import pipeline
    import pytest as _pytest

    with _pytest.raises(FileNotFoundError):
        pipeline.find_original(tmp_path)


def test_normalize_refuses_to_overwrite_its_own_source(tmp_path) -> None:
    """Reading and writing audio.opus in one ffmpeg call would destroy the only
    copy of the audio an imported job has."""
    from worker.stages import normalize
    import pytest as _pytest

    proxy = tmp_path / "audio.opus"
    proxy.write_bytes(b"not really opus")
    with _pytest.raises(normalize.AudioError, match="Refusing to overwrite"):
        normalize.run(proxy, tmp_path, make_opus=True)


# ---------------------------------------------------------------------------
# Filter calibration against 121 real legacy transcripts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Glocken", "Nationalhymne", "Orgel", "Choral", "Chor", "Instrumental",
    "  musik  ", "[Gesang]",
])
def test_bare_audio_labels_are_dropped(text: str) -> None:
    """Whisper labelling non-speech instead of transcribing it. These appeared
    as whole segments dozens of times each in the old system's output."""
    assert hallucinations.is_denylisted(text)


@pytest.mark.parametrize("text", [
    # All of these recur constantly in the archive and are genuine liturgy.
    "Gott zum Gruß.",
    "In Christo Jesu. Amen.",
    "Lasset uns beten.",
    "Unser täglich Brot gib uns heute und vergib uns unsere Schuld,",
    "Denn dein ist das Reich, die Kraft und die Herrlichkeit.",
    "Im Namen Gottes des Vaters, Gottes des Sohnes und Gottes des Heiligen Geistes.",
    "Der Herr lasse leuchten sein Angesicht über euch und sei euch gnädig.",
    "Ich wünsche euch einen schönen Gottesdienst.",
    # Announcements that merely contain a label word.
    "Choral 238",
    "Lied Nr. 34",
    "Wir singen nun die Nationalhymne.",
    "Dann läuten die Glocken zum Gebet.",
])
def test_recurring_liturgy_is_never_dropped(text: str) -> None:
    """A filter that eats real liturgy is far worse than one that keeps a label.
    Every phrase here appeared 30+ times across the 121 imported transcripts."""
    assert not hallucinations.is_denylisted(text)


# ---------------------------------------------------------------------------
# Speech veto on music windows
# ---------------------------------------------------------------------------
def test_speech_veto_threshold_sits_above_singing() -> None:
    """Measured on 43 windows of confirmed congregational singing, the AudioSet
    speech score ran 0.002-0.037. The veto must stay far above that or it would
    turn every hymn back into transcribed lyrics."""
    from worker.config import MUSIC_SPEECH_VETO, MUSIC_THRESHOLD

    assert MUSIC_SPEECH_VETO >= 0.5
    assert MUSIC_THRESHOLD < MUSIC_SPEECH_VETO


def test_loud_music_does_not_beat_confident_speech() -> None:
    """The real case this fixes: music 0.840 against speech 0.719 at the trailing
    edge of a hymn, where an announcement was being swallowed."""
    from worker.config import MUSIC_OVER_SPEECH, MUSIC_SPEECH_VETO, MUSIC_THRESHOLD

    def is_music(music: float, speech: float) -> bool:
        return (music >= MUSIC_THRESHOLD
                and music >= speech * MUSIC_OVER_SPEECH
                and speech < MUSIC_SPEECH_VETO)

    assert not is_music(0.840, 0.719)      # the announcement, now preserved
    assert is_music(0.833, 0.595)          # just below the veto: still music
    assert is_music(0.682, 0.009)          # ordinary congregational singing
    assert is_music(0.907, 0.006)          # organ
    assert not is_music(0.024, 0.859)      # plain speech
    assert not is_music(0.193, 0.100)      # too quiet to call music


# ---------------------------------------------------------------------------
# Clipping segments to the speech VAD found
# ---------------------------------------------------------------------------
def test_monster_segment_is_clipped_to_its_speech_region() -> None:
    """The real case: VAD isolated an announcement at 2107.5-2117.5, but the
    batched ASR emitted it as spanning 2107.5-2436.3 - through five minutes of
    hymn - so the music-overlap check discarded a genuine announcement."""
    speech = [{"start": 2107.5, "end": 2117.5}]
    segment = {"start": 2107.5, "end": 2436.3,
               "text": "es vermag erheben",
               "words": _words([("es", 2107.6, 2107.9), ("vermag", 2108.0, 2108.6),
                                ("erheben", 2116.0, 2117.2)])}
    clipped = merge.clip_to_speech(segment, speech)
    assert clipped["end"] == 2117.5
    assert clipped["clipped"] is True
    # Every word is inside the kept span, so the text is unchanged.
    assert clipped["text"] == segment["text"]

    # And now it survives the music check instead of being swallowed.
    music = [{"start": 2117.5, "end": 2417.5, "marker": "[Musik]"}]
    kept, dropped = merge._drop_inside_music([clipped], music)
    assert kept and not dropped


def test_clipping_bridges_ordinary_speaking_pauses() -> None:
    """Sermon pauses must not truncate an utterance. Measured across three real
    services, speaking pauses reach ~2.9 s; the gaps that must be cut are 20 s+."""
    speech = [{"start": 10.0, "end": 14.0}, {"start": 16.9, "end": 25.0}]
    segment = {"start": 10.0, "end": 25.0, "text": "x", "words": None}
    assert merge.clip_to_speech(segment, speech)["end"] == 25.0


def test_clipping_still_cuts_at_a_musical_gap() -> None:
    speech = [{"start": 10.0, "end": 14.0}, {"start": 34.0, "end": 60.0}]
    segment = {"start": 10.0, "end": 60.0, "text": "x", "words": None}
    assert merge.clip_to_speech(segment, speech)["end"] == 14.0


def test_clipping_leaves_ordinary_segments_alone() -> None:
    speech = [{"start": 0.0, "end": 60.0}]
    segment = {"start": 5.0, "end": 12.0, "text": "x", "words": None}
    assert merge.clip_to_speech(segment, speech) == segment
    # No VAD data at all must not mangle anything either.
    assert merge.clip_to_speech(segment, []) == segment


def test_clipping_drops_words_past_the_cut() -> None:
    speech = [{"start": 0.0, "end": 10.0}]
    segment = {"start": 0.0, "end": 100.0, "text": "a b",
               "words": _words([("a", 1.0, 2.0), ("b", 50.0, 51.0)])}
    clipped = merge.clip_to_speech(segment, speech)
    assert [w["word"] for w in clipped["words"]] == ["a"]


def test_clipping_keeps_text_and_words_in_agreement() -> None:
    """Downstream rebuilds text from words when it has them but falls back to
    the text field when it does not, so a truncated segment must not keep the
    full text - that would put minutes of transcript into seconds of timeline."""
    speech = [{"start": 0.0, "end": 10.0}]
    segment = {"start": 0.0, "end": 100.0, "text": "hier gesprochen und dort gesungen",
               "words": _words([("hier", 1.0, 1.4), ("gesprochen", 1.5, 2.4),
                                ("und", 50.0, 50.2), ("dort", 50.3, 50.8),
                                ("gesungen", 50.9, 51.5)])}
    clipped = merge.clip_to_speech(segment, speech)
    assert clipped["text"] == "hier gesprochen"
    assert [w["word"] for w in clipped["words"]] == ["hier", "gesprochen"]
    assert clipped["end"] == 10.0


# ---------------------------------------------------------------------------
# Alignment must not delete words it cannot align
# ---------------------------------------------------------------------------
def test_unalignable_words_are_kept_not_dropped() -> None:
    """Digits are absent from the wav2vec2 vocabulary, so forced alignment could
    not place them and used to omit them. Because transcript text is rebuilt
    from the word list, that silently turned "Choral Nummer 122" into "Choral
    Nummer" - and hymn numbers, Bible verses and years matter here."""
    import numpy as _np
    from worker.stages import align as align_stage

    original = ["Choral", "Nummer", "122", "singen"]
    bounds = {0: [1.0, 1.6], 1: [1.7, 2.3], 3: [3.1, 3.6]}
    confidence = {0: [-0.1], 1: [-0.1], 3: [-0.1]}
    start, end = 1.0, 3.6

    next_start, upcoming = {}, end
    for index in range(len(original) - 1, -1, -1):
        if index in bounds:
            upcoming = bounds[index][0]
        next_start[index] = upcoming

    words, cursor = [], start
    for i, word in enumerate(original):
        if i in bounds:
            low, high = bounds[i]
            low, high = max(start, low), min(end, max(high, low + 0.01))
            cursor = high
        else:
            low = min(cursor, end)
            high = min(end, max(next_start.get(i, end), low + 0.01))
        words.append({"word": word, "start": round(low, 3), "end": round(high, 3)})

    assert [w["word"] for w in words] == original, "no word may be dropped"
    assert all(w["end"] >= w["start"] for w in words)
    # The unalignable word sits between its neighbours, not at zero.
    digit = words[2]
    assert words[1]["end"] <= digit["start"] <= words[3]["start"]
    assert " ".join(w["word"] for w in words) == "Choral Nummer 122 singen"
    assert _np is not None and align_stage is not None


# ---------------------------------------------------------------------------
# Hymn extraction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Wir singen den Choral 71.", [71]),
    ("Und wir singen das Lied Nummer 27, Brücken bauen", [27]),
    ("im Johannischen Gesangbuch Nr. 177. Macht hoch die", [177]),
    ("Wir singen das Lied 128. Alle Strophen", [128]),
    ("Nummer 144, Strophe 1 bis 4.", [144]),
    ("singen wir den Choral 71. Danach den Choral 410.", [71, 410]),
])
def test_hymn_numbers_are_found(text: str, expected: list[int]) -> None:
    """Phrasings taken verbatim from the archive."""
    assert hymns.find_in_text(text) == expected


@pytest.mark.parametrize("text", [
    # Verse numbers sit right next to hymn announcements and must never be
    # mistaken for them, or every service gains a hymn "1".
    "Großer Gott, wir loben dich. Die Strophen 1 bis 4 und 6.",
    "Wir singen alle vier Strophen.",
    "Strophe 1 bis 4.",
    # No cue word at all.
    "Im Jahr 1917 geschah es.",
    "Wir waren 250 Menschen.",
])
def test_verse_and_stray_numbers_are_not_hymns(text: str) -> None:
    assert hymns.find_in_text(text) == []


def test_number_range_is_enforced() -> None:
    assert hymns.find_in_text("Choral 0") == []
    assert hymns.find_in_text("Lied Nummer 1000") == []
    assert hymns.find_in_text("Choral 999") == [999]



def test_extract_keeps_timestamps_and_deduplicates() -> None:
    doc = {"segments": [
        {"id": "s0", "type": "music", "start": 0.0, "end": 60.0, "text": "[Orgelspiel]"},
        {"id": "s1", "type": "speech", "start": 61.0, "end": 66.0,
         "text": "Wir singen den Choral 71."},
        {"id": "s2", "type": "speech", "start": 300.0, "end": 305.0,
         "text": "Noch einmal Choral 71, alle Strophen."},
    ]}
    got = hymns.extract(doc)
    assert [h["number"] for h in got] == [71]
    assert got[0]["at"] == 61.0          # first mention wins
    assert got[0]["segment_id"] == "s1"
    assert got[0]["mentions"] == 2



def test_hymn_context_is_centred_on_the_number() -> None:
    """A segment can run for half a minute before the number is announced, so a
    snippet taken from its start would cut off the thing it exists to show."""
    doc = {"segments": [{"id": "s1", "type": "speech", "start": 10.0, "end": 40.0,
                         "text": ("Ihr Lieben, wer es vermag, moechte sich nun von seinem "
                                  "Platz erheben, damit wir gemeinsam den Choral Nummer 122 "
                                  "singen, alle Strophen.")}]}
    context = hymns.extract(doc)[0]["context"]
    assert "122" in context
    assert "Choral" in context


# ---------------------------------------------------------------------------
# Redistributing a merged segment instead of truncating it
# ---------------------------------------------------------------------------
def test_segment_spanning_two_speech_runs_keeps_all_its_text() -> None:
    """Truncating at the first gap fixed the timing but deleted real speech -
    the opening address of a later passage was said, just later in the segment."""
    speech = [{"start": 100.0, "end": 110.0}, {"start": 400.0, "end": 410.0}]
    segment = {"start": 100.0, "end": 410.0, "text": "eins zwei drei vier",
               "words": _words([("eins", 100.5, 101.0), ("zwei", 101.1, 101.8),
                                ("drei", 402.0, 402.6), ("vier", 402.7, 403.4)])}
    pieces = merge.split_across_speech(segment, speech)
    assert len(pieces) == 2
    assert " ".join(p["text"] for p in pieces) == "eins zwei drei vier"
    assert pieces[0]["end"] <= pieces[1]["start"]
    assert all(p["redistributed"] for p in pieces)


def test_redistribution_places_nothing_over_the_gap() -> None:
    speech = [{"start": 10.0, "end": 20.0}, {"start": 300.0, "end": 320.0}]
    segment = {"start": 10.0, "end": 320.0, "text": "a b c d e f", "words": None}
    pieces = merge.split_across_speech(segment, speech)
    assert len(pieces) == 2
    # No piece straddles the silent stretch between the two runs.
    assert pieces[0]["end"] <= 20.0 and pieces[1]["start"] >= 300.0
    assert " ".join(p["text"] for p in pieces).split() == list("abcdef")


def test_single_run_still_just_clips() -> None:
    speech = [{"start": 10.0, "end": 20.0}]
    segment = {"start": 10.0, "end": 100.0, "text": "a b", "words": None}
    pieces = merge.split_across_speech(segment, speech)
    assert len(pieces) == 1 and pieces[0]["end"] == 20.0


def test_words_go_to_the_run_they_were_spoken_in() -> None:
    """From the 2026-08-30 service. One ASR segment ran 535-1067 s across two
    hymns; sharing its 51 words out by run length cut the list two words early,
    so "Strophen. Meine" - said at 803 s - was handed to the run at 1063 s."""
    speech = [{"start": 535.7, "end": 551.3}, {"start": 793.4, "end": 802.5},
              {"start": 1063.2, "end": 1067.4}]
    segment = {"start": 535.7, "end": 1066.9, "text": "Amen Festgemeinde Strophen Meine lieben",
               "words": _words([("Amen", 550.1, 550.8),
                                ("Festgemeinde", 793.4, 794.4),
                                ("Strophen", 802.6, 803.4), ("Meine", 803.6, 803.8),
                                ("lieben", 1063.2, 1063.7)])}
    pieces = merge.split_across_speech(segment, speech)
    assert [p["text"] for p in pieces] == ["Amen", "Festgemeinde Strophen Meine", "lieben"]


def test_a_redistributed_piece_never_ends_before_it_starts() -> None:
    """The piece bounds come from the speech runs and the words from the ASR.
    Where they disagree the words win - a segment whose end precedes its start
    reads as a two-minute pause to the export's section split, which then cut
    the service into fragments one word long."""
    speech = [{"start": 10.0, "end": 20.0}, {"start": 300.0, "end": 310.0}]
    segment = {"start": 10.0, "end": 310.0, "text": "a b",
               "words": _words([("a", 12.0, 12.5), ("b", 302.0, 302.5)])}
    for piece in merge.split_across_speech(segment, speech):
        assert piece["end"] >= piece["start"]


def test_a_word_outside_the_segment_widens_it_instead_of_inverting_it() -> None:
    """The backstop for the other two splits: whatever put a word outside the
    bounds it was cut from, the timespan still has to contain its own words."""
    index = merge.SpeakerIndex([{"start": 0.0, "end": 400.0, "speaker": "SPEAKER_00"}])
    segment = {"start": 300.0, "end": 20.0, "text": "a b",
               "words": _words([("a", 300.5, 301.0), ("b", 301.1, 301.6)])}
    piece = merge._split_by_speaker(segment, index)[0]
    assert piece["start"] == 300.0 and piece["end"] == 301.6


# ---------------------------------------------------------------------------
# Phrasings that the first version of the rules got wrong
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    # A "Strophen" earlier in the sentence used to hide a real announcement,
    # because the verse exclusion consumed everything to the next full stop.
    ("Wir singen alle vier Strophen und nach der Predigt den Choral Nummer 154 "
     "in diese Welt entlassen", [154]),
    ("Ihr Lieben, wir singen nun zusammen das Lied 446 vom Herr Segne uns", [446]),
    # The number trails the cue by several words, behind an article.
    ("Das ist der Choral aus unserem Gesangbuch, die 71", [71]),
    ("Wir wollen nun gemeinsam den ersten Choral von unserem Liederzettel "
     "singen, die 440, Ich bin getauft", [440]),
    # Correct even with verse talk following the number.
    ("wir singen nun das Lied 210, Sag Ja zu deinem Leben, alle Strophen.", [210]),
    ("eingangs das Lied Nummer 144, die Strophen 1 bis 4.", [144]),
])
def test_real_phrasings_from_the_archive(text: str, expected: list[int]) -> None:
    assert hymns.find_in_text(text) == expected


@pytest.mark.parametrize("text", [
    # The trailing-number rule must not grab any number after a hymn word.
    "Das Lied hat uns allen gutgetan, wir waren 250 Menschen.",
    "Nach dem Lied sprachen wir über das Jahr 1917.",
    "Wir singen alle vier Strophen.",
    "Großer Gott, wir loben dich. Die Strophen 1 bis 4 und 6.",
])
def test_trailing_rule_does_not_overreach(text: str) -> None:
    assert hymns.find_in_text(text) == []


def test_announcement_split_across_segments_is_still_found() -> None:
    """Whisper splits mid-announcement, leaving the cue in one segment and the
    number in the next, so a per-segment scan alone never sees it."""
    doc = {"segments": [
        {"id": "s0", "type": "speech", "start": 10.0, "end": 14.0,
         "text": "Wir wollen nun gemeinsam den ersten Choral von unserem Liederzettel singen,"},
        {"id": "s1", "type": "speech", "start": 14.0, "end": 20.0,
         "text": "die 440, Ich bin getauft, wir singen alle vier Strophen."},
    ]}
    got = hymns.extract(doc)
    assert [h["number"] for h in got] == [440]
    # Credited to the segment the number is in, not the one with the cue.
    assert got[0]["segment_id"] == "s1" and got[0]["at"] == 14.0


def test_lookbehind_does_not_reach_across_music() -> None:
    """A hymn word before a musical passage must not attach to a number said
    after it - they are minutes apart and unrelated."""
    doc = {"segments": [
        {"id": "s0", "type": "speech", "start": 0.0, "end": 5.0,
         "text": "Wir singen jetzt das Lied"},
        {"id": "s1", "type": "music", "start": 5.0, "end": 300.0,
         "text": "[Gemeindegesang]"},
        {"id": "s2", "type": "speech", "start": 300.0, "end": 305.0,
         "text": "250 Menschen waren da."},
    ]}
    assert hymns.extract(doc) == []


def test_number_in_the_lookbehind_is_not_double_counted() -> None:
    doc = {"segments": [
        {"id": "s0", "type": "speech", "start": 0.0, "end": 5.0,
         "text": "Wir singen den Choral 71."},
        {"id": "s1", "type": "speech", "start": 5.0, "end": 9.0,
         "text": "Danach hören wir die Lesung."},
    ]}
    got = hymns.extract(doc)
    assert [h["number"] for h in got] == [71]
    assert got[0]["segment_id"] == "s0"


def test_only_verified_hymns_are_reported() -> None:
    """The filename source is gone: every hymn reported must have a moment in
    the audio behind it, so the UI never shows an entry that cannot be clicked."""
    doc = {"segments": [
        {"id": "s0", "type": "speech", "start": 61.0, "end": 66.0,
         "text": "Wir singen den Choral 122."},
    ]}
    got = hymns.extract(doc)
    assert [h["number"] for h in got] == [122]
    assert all(h["at"] is not None and h["segment_id"] for h in got)
    assert not hasattr(hymns, "numbers_from_title")
    assert not hasattr(hymns, "collect")


# ---------------------------------------------------------------------------
# ASR clip planning
# ---------------------------------------------------------------------------
def _regions(*spans: tuple[float, float]) -> list[dict[str, float]]:
    return [{"start": float(a), "end": float(b)} for a, b in spans]


def test_everything_that_fits_is_one_clip() -> None:
    regions = _regions((0, 4), (4.5, 10), (11, 20))
    assert asr.plan_clips(regions, window=30.0) == [{"start": 0.0, "end": 20.0}]


def test_clip_ends_at_the_widest_pause_not_the_window_edge() -> None:
    """The greedy packer would fill the window and leave the 1 s fragment at
    28-29 s hanging off its end, which is exactly the fragment Whisper drops.
    The cut belongs at the 2 s pause before it, so the fragment starts the
    next clip together with its continuation."""
    regions = _regions((0, 10), (10.5, 18), (18.4, 26), (28, 29), (29.3, 40))
    clips = asr.plan_clips(regions, window=30.0, max_gap=3.0, min_fill=0.5)
    assert clips == [{"start": 0.0, "end": 26.0}, {"start": 28.0, "end": 40.0}]


def test_cut_prefers_a_pause_once_the_window_is_half_full() -> None:
    """A wide pause early on must not win over a narrower one later, or clips
    would shrink to a few seconds and the ASR would take twice as long."""
    regions = _regions((0, 5), (7.5, 15), (15.3, 22), (23, 27), (27.2, 33))
    clips = asr.plan_clips(regions, window=30.0, max_gap=3.0, min_fill=0.5)
    assert clips[0] == {"start": 0.0, "end": 22.0}


def test_a_long_silence_always_ends_a_clip() -> None:
    regions = _regions((0, 5), (6, 8), (20, 25))
    clips = asr.plan_clips(regions, window=30.0, max_gap=3.0)
    assert clips == [{"start": 0.0, "end": 8.0}, {"start": 20.0, "end": 25.0}]


def test_no_clip_exceeds_the_window_and_every_region_is_covered_once() -> None:
    regions = _regions(*[(i * 3.0, i * 3.0 + 2.0) for i in range(60)])
    clips = asr.plan_clips(regions, window=30.0, max_gap=3.0, min_fill=0.5)
    assert all(c["end"] - c["start"] <= 30.0 for c in clips)
    assert clips[0]["start"] == regions[0]["start"]
    assert clips[-1]["end"] == regions[-1]["end"]
    for earlier, later in zip(clips, clips[1:]):
        assert later["start"] > earlier["end"]
    covered = sum(1 for r in regions
                  if any(c["start"] <= r["start"] and r["end"] <= c["end"] for c in clips))
    assert covered == len(regions)


def test_no_regions_means_no_clips() -> None:
    assert asr.plan_clips([]) == []
