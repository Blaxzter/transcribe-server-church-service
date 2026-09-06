import { useCallback, useRef, useState } from "react";
import * as tus from "tus-js-client";
import { CloudUpload, X } from "lucide-react";
import { de } from "@/i18n/de";
import { cn, formatBytes } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

// Cloudflare Tunnel rejects any single proxied request body over 100 MB, so a
// service recording has to arrive in pieces. 8 MB leaves generous headroom and
// keeps a retry after a dropped connection cheap.
const CHUNK_SIZE = 8 * 1024 * 1024;
const RETRY_DELAYS = [0, 1000, 3000, 5000, 10000, 30000];

interface UploaderProps {
  onComplete: (jobId: string | null) => void;
}

export function Uploader({ onComplete }: UploaderProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadRef = useRef<tus.Upload | null>(null);

  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(
    (selected: File) => {
      setFile(selected);
      setProgress(0);
      setError(null);

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
          uploadRef.current = null;
        },
        onProgress: (sent, total) => setProgress(total ? sent / total : 0),
        onSuccess: () => {
          uploadRef.current = null;
          setFile(null);
          setProgress(0);
          onComplete(jobId);
        },
      });

      uploadRef.current = upload;
      // Resume rather than restart if this exact file was interrupted before.
      upload.findPreviousUploads().then((previous) => {
        if (previous.length) upload.resumeFromPreviousUpload(previous[0]);
        upload.start();
      });
    },
    [onComplete],
  );

  const cancel = useCallback(() => {
    uploadRef.current?.abort(true);
    uploadRef.current = null;
    setFile(null);
    setProgress(0);
  }, []);

  if (file) {
    return (
      <div className="rounded-lg border border-border bg-card p-5">
        <div className="mb-3 flex items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{file.name}</p>
            <p className="text-sm text-muted-foreground">
              {formatBytes(file.size * progress)} / {formatBytes(file.size)}
            </p>
          </div>
          <span className="font-mono text-sm tabular-nums">
            {Math.round(progress * 100)}%
          </span>
          <Button variant="ghost" size="icon" onClick={cancel} aria-label={de.upload.cancel}>
            <X />
          </Button>
        </div>
        <Progress value={progress} />
        <p className="mt-2 text-xs text-muted-foreground">
          {error ?? de.upload.resumeHint}
        </p>
      </div>
    );
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        const dropped = event.dataTransfer.files?.[0];
        if (dropped) start(dropped);
      }}
      onClick={() => inputRef.current?.click()}
      className={cn(
        "cursor-pointer rounded-lg border-2 border-dashed border-border bg-card p-10 text-center transition-colors",
        dragging && "border-primary bg-accent",
      )}
    >
      <CloudUpload className="mx-auto mb-3 size-8 text-muted-foreground" />
      <p className="font-medium">{de.upload.dropzone}</p>
      <p className="mt-1 text-sm text-muted-foreground">
        {de.upload.dropzoneHint}
      </p>
      <p className="mt-3 text-xs text-muted-foreground">{de.upload.formats}</p>
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      <input
        ref={inputRef}
        type="file"
        accept="audio/*,video/*,.m4a,.opus,.mts"
        className="hidden"
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) start(selected);
          event.target.value = "";
        }}
      />
    </div>
  );
}
