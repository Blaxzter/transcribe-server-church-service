import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { AlertCircle, FastForward, Pause, Play, Rewind, RotateCcw } from "lucide-react";
import { api, type Transcript } from "@/lib/api";
import { cn, formatTime } from "@/lib/utils";
import { useTheme } from "@/lib/theme";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";

export interface PlayerControls {
  seekTo: (seconds: number) => void;
  play: () => void;
  pause: () => void;
}

interface WaveformProps {
  jobId: string;
  transcript: Transcript | null;
  onReady?: (controls: PlayerControls) => void;
  onTime?: (seconds: number) => void;
}

const SPEEDS = [0.75, 1, 1.25, 1.5, 2];
const SKIP_SECONDS = 15;

/** Colours live in CSS tokens, so they have to be read back for the canvas. */
function waveColors() {
  const styles = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  const primary = read("--primary", "#2563eb");
  return {
    waveColor: read("--muted-foreground", "#888"),
    progressColor: primary,
    cursorColor: primary,
  };
}

/**
 * Waveform + transport.
 *
 * The performance rule here: the browser must never decode the audio. Peaks are
 * computed server-side and handed to wavesurfer together with the duration,
 * which makes it skip fetch-and-decode entirely and just draw. Playback then
 * streams the 48 kbps Opus proxy through range requests. On a weak laptop this
 * is the difference between an instant render and a multi-second freeze plus a
 * gigabyte of memory.
 */
export function Waveform({ jobId, transcript, onReady, onTime }: WaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const waveRef = useRef<WaveSurfer | null>(null);
  const onTimeRef = useRef(onTime);
  onTimeRef.current = onTime;
  const appliedColorsRef = useRef("");
  const lastEmittedRef = useRef(-1);

  const { resolvedTheme } = useTheme();
  const [ready, setReady] = useState(false);
  const [failure, setFailure] = useState<"load" | "play" | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(transcript?.duration ?? 0);

  /**
   * wavesurfer drives "timeupdate" from a requestAnimationFrame loop, so it
   * fires ~60×/s while playing. `onTime` re-renders the whole detail page
   * including the virtualized transcript, and the clock only ever shows whole
   * seconds, so a tick that stays inside the current half-second is pure
   * waste. Half rather than whole seconds keeps the transcript highlight from
   * trailing the audio by an audible amount.
   * `force` is for seeks, which must land immediately.
   */
  const emitTime = useCallback((time: number, force = false) => {
    const tick = Math.floor(time * 2);
    if (!force && tick === lastEmittedRef.current) return;
    lastEmittedRef.current = tick;
    setCurrentTime(time);
    onTimeRef.current?.(time);
  }, []);

  // playPause()/play() reject when the media never loads. With server peaks the
  // transport is enabled before the audio element has metadata, so a file that
  // is still transcoding or gone surfaces here rather than as an unhandled
  // rejection behind a play button that silently does nothing.
  const startPlayback = useCallback((toggle: boolean) => {
    const wave = waveRef.current;
    if (!wave) return;
    void (toggle ? wave.playPause() : wave.play()).catch(() => {
      setFailure("play");
      setPlaying(false);
    });
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    let instance: WaveSurfer | null = null;
    setReady(false);
    setFailure(null);
    setPlaying(false);
    setCurrentTime(0);
    lastEmittedRef.current = -1;

    (async () => {
      let peaks: Float32Array[] | undefined;
      let peakDuration: number | undefined;
      try {
        const payload = await api.getPeaks(jobId);
        // int8 on the wire; wavesurfer wants -1..1 floats.
        const scaled = new Float32Array(payload.data.length);
        for (let i = 0; i < payload.data.length; i += 1) scaled[i] = payload.data[i] / 127;
        peaks = [scaled];
        peakDuration = payload.duration;
      } catch {
        // No peaks yet: fall back to letting wavesurfer decode. Slower, but the
        // player still works.
      }
      if (cancelled) return;

      const colors = waveColors();
      appliedColorsRef.current = JSON.stringify(colors);

      instance = WaveSurfer.create({
        container,
        url: api.audioUrl(jobId),
        peaks,
        duration: peakDuration,
        height: 88,
        ...colors,
        cursorWidth: 2,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        normalize: false,
        dragToSeek: true,
        mediaControls: false,
      });
      waveRef.current = instance;

      instance.on("ready", () => {
        if (cancelled) return;
        setReady(true);
        setDuration(instance!.getDuration() || peakDuration || 0);
      });
      // With precomputed peaks "ready" can fire before the media element has
      // metadata, so treat decode-free init as ready too.
      if (peaks) setReady(true);

      instance.on("error", () => {
        if (cancelled) return;
        setFailure("load");
        setPlaying(false);
      });
      instance.on("timeupdate", (time: number) => emitTime(time));
      // A seek (waveform click, drag, transport) must show up at once, even
      // when it lands inside the second the throttle has already emitted.
      instance.on("seeking", (time: number) => emitTime(time, true));
      instance.on("play", () => setPlaying(true));
      instance.on("pause", () => setPlaying(false));
      instance.on("finish", () => setPlaying(false));
    })();

    return () => {
      cancelled = true;
      instance?.destroy();
      waveRef.current = null;
    };
  }, [jobId, emitTime]);

  // wavesurfer bakes the colours into the canvas at create time, so a theme
  // switch has to push them back in. ThemeProvider writes <html data-theme> from
  // its own effect, which runs after this one — the frame delay makes sure the
  // new token values are the ones being read.
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const wave = waveRef.current;
      if (!wave) return;
      const colors = waveColors();
      const key = JSON.stringify(colors);
      if (key === appliedColorsRef.current) return;
      appliedColorsRef.current = key;
      wave.setOptions(colors);
    });
    return () => cancelAnimationFrame(frame);
  }, [resolvedTheme, ready]);

  const seekTo = useCallback(
    (seconds: number) => {
      const wave = waveRef.current;
      if (!wave) return;
      const target = Math.max(0, seconds);
      wave.setTime(target);
      emitTime(target, true);
    },
    [emitTime],
  );

  useEffect(() => {
    if (!ready) return;
    onReady?.({
      seekTo,
      play: () => startPlayback(false),
      pause: () => waveRef.current?.pause(),
    });
  }, [ready, seekTo, startPlayback, onReady]);

  const skip = (delta: number) => {
    const wave = waveRef.current;
    if (!wave) return;
    seekTo(Math.min(Math.max(wave.getCurrentTime() + delta, 0), duration || Infinity));
  };

  const changeSpeed = () => {
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
    setSpeed(next);
    waveRef.current?.setPlaybackRate(next, true);
  };

  const ribbon = useMemo(() => buildRibbon(transcript), [transcript]);
  const total = duration || transcript?.duration || 0;
  const usable = ready && failure !== "load";

  return (
    <div className="space-y-3">
      <div className="relative">
        <div
          ref={containerRef}
          className={cn("waveform-host w-full", !usable && "opacity-40")}
        />
        {!usable && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-muted-foreground">
            {failure ? (
              <>
                <AlertCircle className="size-4 text-destructive" />
                <span>
                  {failure === "load" ? de.player.failed : de.player.playbackFailed}
                </span>
              </>
            ) : (
              <span className="animate-soft-pulse">{de.player.loading}</span>
            )}
          </div>
        )}
      </div>

      {ribbon.length > 0 && total > 0 && (
        <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-secondary">
          {ribbon.map((band, index) => (
            <button
              key={index}
              type="button"
              title={band.title}
              aria-label={`${band.title} — ${formatTime(band.start)}`}
              onClick={() => seekTo(band.start)}
              className="absolute top-0 h-full cursor-pointer border-0 p-0 transition-opacity hover:opacity-100"
              style={{
                left: `${(band.start / total) * 100}%`,
                width: `${Math.max(((band.end - band.start) / total) * 100, 0.15)}%`,
                background: band.color,
                opacity: band.kind === "music" ? 0.45 : 1,
              }}
            />
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Tooltip label={de.player.restart}>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => seekTo(0)}
            aria-label={de.player.restart}
            disabled={!usable}
          >
            <RotateCcw />
          </Button>
        </Tooltip>
        <Tooltip label={de.player.skipBack}>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => skip(-SKIP_SECONDS)}
            aria-label={de.player.skipBack}
            disabled={!usable}
          >
            <Rewind />
          </Button>
        </Tooltip>
        <Button
          size="icon"
          onClick={() => startPlayback(true)}
          aria-label={playing ? de.player.pause : de.player.play}
          disabled={!usable}
        >
          {playing ? <Pause /> : <Play />}
        </Button>
        <Tooltip label={de.player.skipForward}>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => skip(SKIP_SECONDS)}
            aria-label={de.player.skipForward}
            disabled={!usable}
          >
            <FastForward />
          </Button>
        </Tooltip>

        <span className="ml-1 font-mono text-sm tabular-nums text-muted-foreground">
          {formatTime(currentTime)} / {formatTime(total)}
        </span>

        <Tooltip label={de.player.speed} className="ml-auto">
          <Button
            variant="outline"
            size="sm"
            className="font-mono"
            onClick={changeSpeed}
            aria-label={de.player.speed}
            disabled={!usable}
          >
            {speed.toLocaleString("de-DE")}×
          </Button>
        </Tooltip>
      </div>
    </div>
  );
}

interface Band {
  start: number;
  end: number;
  color: string;
  kind: "speech" | "music";
  title: string;
}

/**
 * A colour band per speaker turn. Built from the transcript rather than drawn as
 * wavesurfer regions: a service has thousands of segments and the regions plugin
 * would create a DOM node for each. Merging consecutive same-speaker segments
 * typically leaves well under 200 bands.
 */
function buildRibbon(transcript: Transcript | null): Band[] {
  if (!transcript) return [];
  const bands: Band[] = [];
  for (const segment of transcript.segments) {
    const isMusic = segment.type === "music";
    const key = isMusic ? segment.marker ?? de.transcript.music : segment.speaker ?? "unknown";
    const title = keyTitle(transcript, key, isMusic);
    const previous = bands[bands.length - 1];
    if (previous && previous.title === title && segment.start - previous.end < 1.5) {
      previous.end = segment.end;
      continue;
    }
    bands.push({
      start: segment.start,
      end: segment.end,
      kind: isMusic ? "music" : "speech",
      color: isMusic
        ? "var(--color-muted-foreground)"
        : transcript.speakers[key]?.color ?? "var(--color-muted-foreground)",
      title,
    });
  }
  return bands;
}

function keyTitle(transcript: Transcript, key: string, isMusic: boolean): string {
  if (isMusic) return key;
  return transcript.speakers[key]?.label ?? de.transcript.speakerUnknown;
}
