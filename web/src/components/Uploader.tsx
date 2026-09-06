import { useCallback, useEffect, useRef, useState } from "react";
import * as tus from "tus-js-client";
import { CheckCircle2, CloudUpload, RotateCcw, X } from "lucide-react";
import { de } from "@/i18n/de";
import { cn, formatBytes, formatTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

// Cloudflare Tunnel rejects any single proxied request body over 100 MB, so a
// service recording has to arrive in pieces. 8 MB leaves generous headroom and
// keeps a retry after a dropped connection cheap.
const CHUNK_SIZE = 8 * 1024 * 1024;
const RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 30000];
const DONE_NOTICE_MS = 6000;

// Recordings often arrive from a camera or recorder that leaves the MIME type
// empty, so the extension is the only hint we get.
const EXTENSIONS = [
  "mp3", "wav", "m4a", "flac", "ogg", "oga", "opus", "aac", "wma", "aiff", "amr",
  "mp4", "mov", "mts", "m2ts", "mkv", "avi", "webm",
];

function isSupported(file: File): boolean {
  if (file.type.startsWith("audio/") || file.type.startsWith("video/")) return true;
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return EXTENSIONS.includes(extension);
}

interface UploaderProps {
  onComplete: (jobId: string | null) => void;
}

export function Uploader({ onComplete }: UploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<tus.Upload | null>(null);
  const startedAtRef = useRef(0);
  const noticeTimerRef = useRef<number | undefined>(undefined);

  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [remaining, setRemaining] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => () => window.clearTimeout(noticeTimerRef.current), []);

  const start = useCallback(
    (selected: File) => {
      setFile(selected);
      setProgress(0);
      setRemaining(null);
      setError(null);
      setDone(false);
      startedAtRef.current = Date.now();

      // The API returns the created job id on the PATCH that completes the
      // upload; capturing it here means we can jump straight to the new job.
      let jobId: string | null = null;

      const upload = new tus.Upload(selected, {
        endpoint: "/files",
        chunkSize: CHUNK_SIZE,
        retryDelays: RETRY_DELAYS,
        removeFingerprintOnSuccess: true,
        metadata: { filename: selected.name, filetype: selected.type || "audio" },
        onAfterResponse: (_request, response) => {
          jobId = response.getHeader("Transcribe-Job-Id") ?? jobId;
        },
        onError: (uploadError) => {
          setError(`${de.upload.failed}: ${uploadError.message}`);
          setRemaining(null);
          uploadRef.current = null;
        },
        onProgress: (sent, total) => {
          setProgress(total ? sent / total : 0);
          const elapsed = (Date.now() - startedAtRef.current) / 1000;
          // Below a few seconds the throughput estimate is pure noise.
          setRemaining(
            elapsed > 3 && sent > 0 ? Math.round(((total - sent) * elapsed) / sent) : null,
          );
        },
        onSuccess: () => {
          uploadRef.current = null;
          setFile(null);
          setProgress(0);
          setRemaining(null);
          setDone(true);
          window.clearTimeout(noticeTimerRef.current);
          noticeTimerRef.current = window.setTimeout(() => setDone(false), DONE_NOTICE_MS);
          onComplete(jobId);
        },
      });

      uploadRef.current = upload;
      // Resume rather than restart if this exact file was interrupted before; a
      // storage failure while looking must not swallow the upload.
      upload.findPreviousUploads().then(
        (previous) => {
          if (previous.length) upload.resumeFromPreviousUpload(previous[0]);
          upload.start();
        },
        () => upload.start(),
      );
    },
    [onComplete],
  );

  const select = useCallback(
    (selected: File) => {
      if (!isSupported(selected)) {
        setFile(null);
        setError(de.upload.unsupported);
        return;
      }
      start(selected);
    },
    [start],
  );

  const cancel = useCallback(() => {
    uploadRef.current?.abort(true);
    uploadRef.current = null;
    setFile(null);
    setProgress(0);
    setRemaining(null);
    setError(null);
  }, []);

  if (file) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="mb-3 flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{file.name}</p>
            <p className="text-sm text-muted-foreground">
              {formatBytes(file.size * progress)} {de.common.of} {formatBytes(file.size)}
            </p>
          </div>
          <span className="font-mono text-sm tabular-nums">
            {Math.round(progress * 100)}%
          </span>
          {error ? (
            <Button variant="outline" size="sm" onClick={() => start(file)}>
              <RotateCcw />
              {de.upload.retry}
            </Button>
          ) : null}
          <Button variant="ghost" size="icon" onClick={cancel} aria-label={de.upload.cancel}>
            <X />
          </Button>
        </div>
        <Progress value={progress} />
        <p
          aria-live="polite"
          className={cn("mt-2 text-xs", error ? "text-destructive" : "text-muted-foreground")}
        >
          {error ??
            (remaining !== null
              ? `${formatTime(remaining)} ${de.upload.remaining}`
              : de.upload.resumeHint)}
        </p>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const dropped = event.dataTransfer.files?.[0];
          if (dropped) select(dropped);
        }}
        aria-label={de.upload.title}
        className={cn(
          "w-full rounded-lg border-2 border-dashed border-border bg-card p-10 text-center transition-colors",
          "hover:border-primary/60 hover:bg-accent/50",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          dragging && "border-primary bg-accent",
        )}
      >
        <CloudUpload
          className={cn(
            "mx-auto mb-3 size-8 text-muted-foreground transition-transform",
            dragging && "-translate-y-0.5 text-primary",
          )}
        />
        <p className="font-medium">
          {dragging ? de.upload.dropActive : de.upload.dropzone}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{de.upload.dropzoneHint}</p>
        <p className="mt-3 text-xs text-muted-foreground">{de.upload.formats}</p>
      </button>

      {done && (
        <p
          aria-live="polite"
          className="mt-3 flex items-center justify-center gap-2 text-sm text-success"
        >
          <CheckCircle2 className="size-4" />
          {de.upload.done} — {de.upload.queued}
        </p>
      )}
      {error && (
        <p aria-live="polite" className="mt-3 text-center text-sm text-destructive">
          {error}
        </p>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="audio/*,video/*,.m4a,.opus,.mts"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) select(selected);
          event.target.value = "";
        }}
      />
    </div>
  );
}
