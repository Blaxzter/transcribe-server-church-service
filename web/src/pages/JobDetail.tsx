import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, Check, Download, Loader2, RefreshCw } from "lucide-react";
import {
  api,
  subscribeToJob,
  type Job,
  type Stage,
  type Transcript,
} from "@/lib/api";
import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";
import { Waveform, type PlayerControls } from "@/components/Waveform";
import { TranscriptView } from "@/components/Transcript";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";

const STAGE_ORDER: Stage[] = [
  "normalize", "peaks", "music", "vad", "asr", "align", "diarize", "merge", "summarize",
];

const EXPORTS: { format: string; label: string }[] = [
  { format: "docx", label: de.exportMenu.docx },
  { format: "md", label: de.exportMenu.md },
  { format: "txt", label: de.exportMenu.txt },
  { format: "srt", label: de.exportMenu.srt },
  { format: "vtt", label: de.exportMenu.vtt },
];

type SaveState = "idle" | "saving" | "saved" | "error";

export function JobDetailPage() {
  const { id = "" } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [doc, setDoc] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const controlsRef = useRef<PlayerControls | null>(null);

  // --- data ---------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    api
      .getJob(id)
      .then((value) => !cancelled && setJob(value))
      .catch(() => !cancelled && setError(de.errors.notFound));
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!job?.has_transcript) return;
    let cancelled = false;
    api
      .getTranscript(id)
      .then((value) => !cancelled && setDoc(value))
      .catch(() => !cancelled && setError(de.errors.loadFailed));
    return () => {
      cancelled = true;
    };
  }, [id, job?.has_transcript]);

  // Live progress while the job is still being processed.
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "failed") return;
    return subscribeToJob(id, (event) => {
      setJob((current) => (current ? { ...current, ...event } : current));
    });
  }, [id, job?.status]);

  // --- editing ------------------------------------------------------------
  const withSaveState = useCallback(async (action: () => Promise<Transcript>) => {
    setSaveState("saving");
    try {
      const updated = await action();
      setDoc(updated);
      setSaveState("saved");
      window.setTimeout(() => setSaveState("idle"), 1800);
    } catch {
      setSaveState("error");
    }
  }, []);

  const editSegment = useCallback(
    (segmentId: string, text: string) =>
      withSaveState(() => api.patchTranscript(id, { segments: [{ id: segmentId, text }] })),
    [id, withSaveState],
  );

  const renameSpeaker = useCallback(
    (speakerId: string, label: string) =>
      withSaveState(() => api.patchTranscript(id, { speakers: { [speakerId]: { label } } })),
    [id, withSaveState],
  );

  const saveTitle = useCallback(
    async (title: string, serviceDate: string | null) => {
      const updated = await api.patchJob(id, { title, service_date: serviceDate });
      setJob(updated);
    },
    [id],
  );

  const handleReady = useCallback((controls: PlayerControls) => {
    controlsRef.current = controls;
  }, []);

  const seek = useCallback((seconds: number) => {
    controlsRef.current?.seekTo(seconds);
    setCurrentTime(seconds);
  }, []);

  if (error) {
    return (
      <Shell>
        <Card className="p-8 text-center">
          <AlertCircle className="mx-auto mb-3 size-6 text-destructive" />
          <p>{error}</p>
        </Card>
      </Shell>
    );
  }

  if (!job) {
    return (
      <Shell>
        <p className="py-16 text-center text-sm text-muted-foreground">…</p>
      </Shell>
    );
  }

  return (
    <Shell>
      <JobHeader job={job} saveState={saveState} onSave={saveTitle} />

      {job.status === "failed" && <FailurePanel job={job} onRetry={setJob} />}

      {(job.status === "queued" || job.status === "running") && <ProgressPanel job={job} />}

      {job.status === "done" && (
        <div className="space-y-4">
          <Card>
            <CardContent className="pt-5">
              <Waveform
                jobId={id}
                transcript={doc}
                onReady={handleReady}
                onTime={setCurrentTime}
              />
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <Card className="flex h-[min(70vh,44rem)] flex-col overflow-hidden">
              {doc ? (
                <TranscriptView
                  doc={doc}
                  currentTime={currentTime}
                  onSeek={seek}
                  onEditSegment={editSegment}
                  onRenameSpeaker={renameSpeaker}
                />
              ) : (
                <p className="p-8 text-center text-sm text-muted-foreground">…</p>
              )}
            </Card>

            <div className="space-y-4">
              <SummaryPanel doc={doc} />
              <SpeakerLegend doc={doc} />
              <ExportPanel jobId={id} />
            </div>
          </div>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-6">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:underline"
      >
        <ArrowLeft className="size-4" />
        {de.nav.back}
      </Link>
      {children}
    </div>
  );
}

function JobHeader({
  job,
  saveState,
  onSave,
}: {
  job: Job;
  saveState: SaveState;
  onSave: (title: string, serviceDate: string | null) => Promise<void>;
}) {
  const [title, setTitle] = useState(job.title);
  const [serviceDate, setServiceDate] = useState(job.service_date ?? "");

  useEffect(() => {
    setTitle(job.title);
    setServiceDate(job.service_date ?? "");
  }, [job.id, job.title, job.service_date]);

  const commit = () => {
    if (title !== job.title || (serviceDate || null) !== job.service_date) {
      void onSave(title, serviceDate || null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onBlur={commit}
        placeholder={de.job.titlePlaceholder}
        className="h-10 max-w-md flex-1 border-transparent bg-transparent px-0 text-lg font-semibold shadow-none focus-visible:ring-0"
      />
      <Input
        type="date"
        value={serviceDate}
        onChange={(event) => setServiceDate(event.target.value)}
        onBlur={commit}
        className="w-40"
      />
      <span
        className={cn(
          "text-xs text-muted-foreground transition-opacity",
          saveState === "idle" && "opacity-0",
        )}
      >
        {saveState === "saving" && de.job.saving}
        {saveState === "saved" && de.job.saved}
        {saveState === "error" && de.job.saveFailed}
      </span>
    </div>
  );
}

function ProgressPanel({ job }: { job: Job }) {
  const activeIndex = job.stage ? STAGE_ORDER.indexOf(job.stage) : -1;
  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex items-center gap-2">
          <Loader2 className="size-4 animate-spin text-primary" />
          <p className="text-sm">
            {de.job.processing} <strong>{de.job.processingTime}</strong>
          </p>
        </div>
        <Progress value={job.progress} indeterminate={job.status === "queued"} />
        <ol className="grid gap-1.5 sm:grid-cols-3">
          {STAGE_ORDER.map((stage, index) => (
            <li
              key={stage}
              className={cn(
                "flex items-center gap-2 text-sm",
                index < activeIndex && "text-muted-foreground line-through",
                index === activeIndex && "font-medium text-foreground",
                index > activeIndex && "text-muted-foreground opacity-60",
              )}
            >
              {index < activeIndex ? (
                <Check className="size-3.5 shrink-0" />
              ) : index === activeIndex ? (
                <Loader2 className="size-3.5 shrink-0 animate-spin" />
              ) : (
                <span className="size-3.5 shrink-0 rounded-full border border-current opacity-40" />
              )}
              {de.stages[stage]}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function FailurePanel({ job, onRetry }: { job: Job; onRetry: (job: Job) => void }) {
  const [busy, setBusy] = useState(false);
  return (
    <Card className="border-destructive/40">
      <CardContent className="space-y-3 pt-5">
        <div className="flex items-center gap-2 font-medium text-destructive">
          <AlertCircle className="size-4" />
          {de.job.failedTitle}
        </div>
        {job.error && (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
            {job.error}
          </pre>
        )}
        <Button
          variant="outline"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              onRetry(await api.retryJob(job.id));
            } finally {
              setBusy(false);
            }
          }}
        >
          <RefreshCw className={cn(busy && "animate-spin")} />
          {de.jobs.retry}
        </Button>
      </CardContent>
    </Card>
  );
}

function SummaryPanel({ doc }: { doc: Transcript | null }) {
  const outline = doc?.outline ?? [];
  if (!doc?.summary) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{de.summary.title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{de.summary.missing}</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{de.summary.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm leading-relaxed">{doc.summary}</p>
        {outline.length > 0 && (
          <>
            <h4 className="text-sm font-medium">{de.summary.outline}</h4>
            <ul className="list-disc space-y-1 pl-4 text-sm text-muted-foreground">
              {outline.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SpeakerLegend({ doc }: { doc: Transcript | null }) {
  const speakers = useMemo(() => Object.entries(doc?.speakers ?? {}), [doc]);
  if (!speakers.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{de.jobs.speakers}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {speakers.map(([id, speaker]) => (
          <span
            key={id}
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
            style={{ color: speaker.color, background: `${speaker.color}1a` }}
          >
            <span className="size-1.5 rounded-full" style={{ background: speaker.color }} />
            {speaker.label}
          </span>
        ))}
      </CardContent>
    </Card>
  );
}

function ExportPanel({ jobId }: { jobId: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{de.exportMenu.title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {EXPORTS.map((entry) => (
          <Button
            key={entry.format}
            variant="outline"
            size="sm"
            className="justify-start"

            onClick={() => {
              window.location.href = api.exportUrl(jobId, entry.format);
            }}
          >
            <Download />
            {entry.label}
          </Button>
        ))}
        <Button
          variant="ghost"
          size="sm"
          className="justify-start"
          onClick={() => {
            window.location.href = api.originalUrl(jobId);
          }}
        >
          <Download />
          {de.exportMenu.original}
        </Button>
      </CardContent>
    </Card>
  );
}
