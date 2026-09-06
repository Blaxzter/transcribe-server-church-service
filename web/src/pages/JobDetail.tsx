import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, FileText, RefreshCw } from "lucide-react";
import { api, subscribeToJob, type Job, type JobStatus, type Transcript } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";
import { Waveform, type PlayerControls } from "@/components/Waveform";
import { TranscriptView } from "@/components/Transcript";
import {
  DetailSidebar,
  defaultDetailTab,
  type DetailTab,
} from "@/components/detail/DetailSidebar";
import {
  DetailSkeleton,
  SidebarSkeleton,
  TranscriptSkeleton,
} from "@/components/detail/DetailSkeleton";
import { FailurePanel } from "@/components/detail/FailurePanel";
import { JobHeader, type SaveState } from "@/components/detail/JobHeader";
import { ProgressPanel } from "@/components/detail/ProgressPanel";
import { DETAIL_GRID, SIDEBAR_PANE, TRANSCRIPT_PANE } from "@/components/detail/panes";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/components/ui/toast";

const SAVED_FLASH_MS = 1800;

/** Statuses the job never leaves — nothing more will arrive over the stream. */
const TERMINAL: JobStatus[] = ["done", "failed", "canceled"];

export function JobDetailPage() {
  const { id = "" } = useParams();
  const { toast } = useToast();
  const [job, setJob] = useState<Job | null>(null);
  const [doc, setDoc] = useState<Transcript | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [docAttempt, setDocAttempt] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [tab, setTab] = useState<DetailTab | null>(null);
  const controlsRef = useRef<PlayerControls | null>(null);
  const savedTimer = useRef<number | undefined>(undefined);

  const status = job?.status;
  const hasTranscript = job?.has_transcript ?? false;
  const legacy = doc?.source === "legacy-import";

  useEffect(() => () => window.clearTimeout(savedTimer.current), []);

  // --- data ---------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setJob(null);
    setDoc(null);
    setJobError(null);
    setDocError(null);
    setTab(null);
    api
      .getJob(id)
      .then((value) => !cancelled && setJob(value))
      .catch(() => !cancelled && setJobError(de.job.notFound));
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!hasTranscript) return;
    let cancelled = false;
    setDocError(null);
    api
      .getTranscript(id)
      .then((value) => !cancelled && setDoc(value))
      .catch(() => !cancelled && setDocError(de.errors.loadFailed));
    return () => {
      cancelled = true;
    };
  }, [id, hasTranscript, docAttempt]);

  // The sidebar opens on whatever this recording actually has, decided once —
  // as soon as the transcript state is known — and owned by the user after
  // that. Deriving it on every render swapped the visible panel from
  // Zusammenfassung to Export under the user the moment a legacy import (no
  // summary, no speakers) resolved.
  const transcriptSettled =
    status === "done" && (!hasTranscript || doc !== null || docError !== null);
  useEffect(() => {
    if (!transcriptSettled) return;
    setTab((current) => current ?? defaultDetailTab(doc));
  }, [transcriptSettled, doc]);

  // Live progress while the job is still being processed. The stream carries
  // partial jobs, so the finished job is fetched once in full at the end.
  useEffect(() => {
    if (!status || TERMINAL.includes(status)) return;
    return subscribeToJob(id, (event) => {
      setJob((current) => (current ? { ...current, ...event } : current));
      if (event.status && TERMINAL.includes(event.status)) {
        void api
          .getJob(id)
          .then((value) => {
            setJob(value);
            // A reprocessed job keeps has_transcript, so ask for the new one.
            setDocAttempt((attempt) => attempt + 1);
          })
          .catch(() => undefined);
      }
    });
  }, [id, status]);

  // --- editing ------------------------------------------------------------
  const flashSaved = useCallback(() => {
    setSaveState("saved");
    window.clearTimeout(savedTimer.current);
    savedTimer.current = window.setTimeout(() => setSaveState("idle"), SAVED_FLASH_MS);
  }, []);

  const withSaveState = useCallback(
    async (action: () => Promise<Transcript>) => {
      setSaveState("saving");
      try {
        setDoc(await action());
        flashSaved();
      } catch {
        setSaveState("error");
        toast({ title: de.toast.saveFailed, variant: "destructive" });
      }
    },
    [flashSaved, toast],
  );

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
      setSaveState("saving");
      try {
        setJob(await api.patchJob(id, { title, service_date: serviceDate }));
        flashSaved();
      } catch {
        setSaveState("error");
        toast({ title: de.toast.saveFailed, variant: "destructive" });
      }
    },
    [id, flashSaved, toast],
  );

  const retry = useCallback(async () => {
    try {
      const updated = await api.retryJob(id);
      setDoc(null);
      setJob(updated);
      toast({ title: de.toast.retryQueued });
    } catch {
      toast({ title: de.toast.retryFailed, variant: "destructive" });
    }
  }, [id, toast]);

  const handleReady = useCallback((controls: PlayerControls) => {
    controlsRef.current = controls;
  }, []);

  const seek = useCallback((seconds: number) => {
    controlsRef.current?.seekTo(seconds);
    setCurrentTime(seconds);
  }, []);

  if (jobError) {
    return (
      <Shell>
        <Card>
          <EmptyState
            icon={<AlertCircle />}
            title={jobError}
            action={
              <Link to="/" className={buttonVariants({ variant: "outline" })}>
                {de.nav.back}
              </Link>
            }
          />
        </Card>
      </Shell>
    );
  }

  if (!job) {
    return (
      <Shell>
        <DetailSkeleton />
      </Shell>
    );
  }

  return (
    <Shell>
      <JobHeader
        job={job}
        legacy={legacy}
        saveState={saveState}
        onSave={(title, serviceDate) => void saveTitle(title, serviceDate)}
      />

      {job.status === "failed" && <FailurePanel job={job} onRetry={retry} />}

      {(job.status === "queued" || job.status === "running") && <ProgressPanel job={job} />}

      {job.status === "done" && (
        <>
          {job.has_audio && (
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
          )}

          <div className={DETAIL_GRID}>
            <Card className={cn("flex flex-col overflow-hidden", TRANSCRIPT_PANE)}>
              {doc ? (
                <TranscriptView
                  doc={doc}
                  currentTime={currentTime}
                  onSeek={seek}
                  onEditSegment={editSegment}
                  onRenameSpeaker={renameSpeaker}
                />
              ) : docError ? (
                <EmptyState
                  className="m-auto"
                  icon={<AlertCircle />}
                  title={docError}
                  action={
                    <Button
                      variant="outline"
                      onClick={() => setDocAttempt((attempt) => attempt + 1)}
                    >
                      <RefreshCw />
                      {de.common.retry}
                    </Button>
                  }
                />
              ) : hasTranscript ? (
                <TranscriptSkeleton />
              ) : (
                <EmptyState
                  className="m-auto"
                  icon={<FileText />}
                  title={de.transcript.empty}
                />
              )}
            </Card>

            {tab ? (
              <DetailSidebar
                job={job}
                doc={doc}
                legacy={legacy}
                value={tab}
                onValueChange={setTab}
                onSeek={seek}
                onRenameSpeaker={renameSpeaker}
                className={SIDEBAR_PANE}
              />
            ) : (
              <Card className={cn("flex flex-col overflow-hidden", SIDEBAR_PANE)}>
                <SidebarSkeleton />
              </Card>
            )}
          </div>
        </>
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
