import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import { Pause, Play, Rewind, FastForward } from "lucide-react";
import { api, type Transcript } from "@/lib/api";
import { cn, formatTime } from "@/lib/utils";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";

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

  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(transcript?.duration ?? 0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let cancelled = false;
    let instance: WaveSurfer | null = null;

    (async () => {
      const styles = getComputedStyle(document.documentElement);
      const muted = styles.getPropertyValue("--muted-foreground").trim() || "#888";
      const primary = styles.getPropertyValue("--primary").trim() || "#2563eb";

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

      instance = WaveSurfer.create({
        container,
        url: api.audioUrl(jobId),
        peaks,
        duration: peakDuration,
        height: 88,
        waveColor: muted,
        progressColor: primary,
        cursorColor: primary,
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

      instance.on("timeupdate", (time: number) => {
        setCurrentTime(time);
        onTimeRef.current?.(time);
      });
      instance.on("play", () => setPlaying(true));
      instance.on("pause", () => setPlaying(false));
      instance.on("finish", () => setPlaying(false));
    })();

    return () => {
      cancelled = true;
      instance?.destroy();
      waveRef.current = null;
    };
  }, [jobId]);

  const seekTo = useCallback((seconds: number) => {
    const wave = waveRef.current;
    if (!wave) return;
    wave.setTime(Math.max(0, seconds));
    setCurrentTime(seconds);
  }, []);

  useEffect(() => {
    if (!ready) return;
    onReady?.({
      seekTo,
      play: () => waveRef.current?.play(),
      pause: () => waveRef.current?.pause(),
    });
  }, [ready, seekTo, onReady]);

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

  return (
    <div className="space-y-3">
      <div className="relative">
        <div ref={containerRef} className="waveform-host w-full" />
        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            <span className="animate-soft-pulse">{de.player.loading}</span>
          </div>
        )}
      </div>

      {ribbon.length > 0 && total > 0 && (
        <div
          className="relative h-2.5 w-full overflow-hidden rounded-full bg-secondary"
          role="presentation"
        >
          {ribbon.map((band, index) => (
            <button
              key={index}
              type="button"
              title={band.title}
              onClick={() => seekTo(band.start)}
              className={cn(
                "absolute top-0 h-full cursor-pointer border-0 p-0",
                band.kind === "music" && "opacity-45",
              )}
              style={{
                left: `${(band.start / total) * 100}%`,
                width: `${Math.max(((band.end - band.start) / total) * 100, 0.15)}%`,
                background: band.color,
              }}
            />
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={() => skip(-SKIP_SECONDS)}
                aria-label={de.player.skipBack} disabled={!ready}>
          <Rewind />
        </Button>
        <Button size="icon" onClick={() => waveRef.current?.playPause()}
                aria-label={playing ? de.player.pause : de.player.play} disabled={!ready}>
          {playing ? <Pause /> : <Play />}
        </Button>
        <Button variant="ghost" size="icon" onClick={() => skip(SKIP_SECONDS)}
                aria-label={de.player.skipForward} disabled={!ready}>
          <FastForward />
        </Button>

        <span className="ml-1 font-mono text-sm tabular-nums text-muted-foreground">
          {formatTime(currentTime)} / {formatTime(total)}
        </span>

        <Button variant="outline" size="sm" className="ml-auto font-mono"
                onClick={changeSpeed} aria-label={de.player.speed} disabled={!ready}>
          {speed.toLocaleString("de-DE")}×
        </Button>
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
    const key = isMusic ? segment.marker ?? "music" : segment.speaker ?? "unknown";
    const previous = bands[bands.length - 1];
    if (previous && previous.title === keyTitle(transcript, key, isMusic)
        && segment.start - previous.end < 1.5) {
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
      title: keyTitle(transcript, key, isMusic),
    });
  }
  return bands;
}

function keyTitle(transcript: Transcript, key: string, isMusic: boolean): string {
  if (isMusic) return key;
  return transcript.speakers[key]?.label ?? key;
}
