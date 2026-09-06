import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertCircle, CheckCircle2, Clock, Loader2, Trash2, Users } from "lucide-react";
import { api, type Job } from "@/lib/api";
import { de } from "@/i18n/de";
import { formatDateTime, formatDuration } from "@/lib/utils";
import { Uploader } from "@/components/Uploader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

const POLL_INTERVAL_MS = 3000;

export function JobsPage() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.listJobs();
      setJobs(data.jobs);
      setError(null);
    } catch {
      setError(de.errors.loadFailed);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something is actually in flight. One list request is
  // cheaper and simpler than an EventSource per row.
  useEffect(() => {
    const active = jobs.some((job) => job.status === "queued" || job.status === "running");
    if (!active) {
      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = null;
      return;
    }
    timerRef.current = window.setInterval(load, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, [jobs, load]);

  const remove = async (job: Job) => {
    if (!window.confirm(de.jobs.deleteConfirm)) return;
    await api.deleteJob(job.id);
    setJobs((current) => current.filter((item) => item.id !== job.id));
  };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-8 px-4 py-8">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">{de.upload.title}</h1>
        <Uploader
          onComplete={(jobId) => {
            void load();
            if (jobId) navigate(`/job/${jobId}`);
          }}
        />
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">{de.jobs.listTitle}</h2>

        {loading && (
          <p className="py-8 text-center text-sm text-muted-foreground">…</p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}

        {!loading && jobs.length === 0 && (
          <Card className="p-10 text-center">
            <p className="font-medium">{de.jobs.empty}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {de.jobs.emptyHint}
            </p>
          </Card>
        )}

        <ul className="space-y-3">
          {jobs.map((job) => (
            <li key={job.id}>
              <Card className="p-4 transition-colors hover:border-ring">
                <div className="flex items-start gap-4">
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/job/${job.id}`}
                      className="block truncate font-medium hover:underline"
                    >
                      {job.title || de.jobs.untitled}
                    </Link>
                    <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
                      <span className="inline-flex items-center gap-1.5">
                        <Clock className="size-3.5" />
                        {formatDuration(job.duration_s)}
                      </span>
                      {job.speaker_count ? (
                        <span className="inline-flex items-center gap-1.5">
                          <Users className="size-3.5" />
                          {job.speaker_count} {de.jobs.speakers}
                        </span>
                      ) : null}
                      <span>{formatDateTime(job.created_at)}</span>
                    </div>
                  </div>

                  <StatusBadge job={job} />

                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => void remove(job)}
                    aria-label={de.jobs.delete}
                  >
                    <Trash2 className="text-muted-foreground" />
                  </Button>
                </div>

                {(job.status === "running" || job.status === "queued") && (
                  <div className="mt-3 space-y-1.5">
                    <Progress
                      value={job.progress}
                      indeterminate={job.status === "queued"}
                    />
                    <p className="text-xs text-muted-foreground">
                      {job.message ?? de.status[job.status]}
                    </p>
                  </div>
                )}

                {job.status === "failed" && job.error && (
                  <p className="mt-3 rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    {job.error}
                  </p>
                )}
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function StatusBadge({ job }: { job: Job }) {
  switch (job.status) {
    case "done":
      return (
        <Badge variant="success">
          <CheckCircle2 className="size-3.5" />
          {de.status.done}
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive">
          <AlertCircle className="size-3.5" />
          {de.status.failed}
        </Badge>
      );
    case "running":
      return (
        <Badge variant="warning">
          <Loader2 className="size-3.5 animate-spin" />
          {de.status.running}
        </Badge>
      );
    default:
      return (
        <Badge>
          <Clock className="size-3.5" />
          {de.status[job.status] ?? job.status}
        </Badge>
      );
  }
}
