import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Inbox, SearchX } from "lucide-react";
import { api, type Job } from "@/lib/api";
import { de } from "@/i18n/de";
import { Uploader } from "@/components/Uploader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { useToast } from "@/components/ui/toast";
import { JobList } from "@/components/jobs/JobList";
import { JobListSkeleton } from "@/components/jobs/JobListSkeleton";
import { JobsToolbar } from "@/components/jobs/JobsToolbar";
import {
  isActive,
  isDateSort,
  selectJobs,
  totalDuration,
  type JobFilter,
  type JobSort,
} from "@/components/jobs/jobFilters";

const POLL_INTERVAL_MS = 3000;

export function JobsPage() {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<JobFilter>("all");
  const [sort, setSort] = useState<JobSort>("newest");
  const [pendingDelete, setPendingDelete] = useState<Job | null>(null);

  // Every list response carries the sequence it was issued with; a newer one
  // (or a delete) invalidates whatever is still in flight, so a poll started
  // before a deletion can never resurrect the removed row.
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const data = await api.listJobs();
      if (seq !== seqRef.current) return;
      setJobs(data.jobs);
      setError(null);
    } catch {
      if (seq !== seqRef.current) return;
      setError(de.errors.loadFailed);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something is actually in flight. One list request is
  // cheaper and simpler than an EventSource per row; keying the effect on the
  // boolean keeps every answer from restarting the timer.
  const hasActive = jobs.some(isActive);
  useEffect(() => {
    if (!hasActive) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [hasActive, load]);

  const visible = useMemo(
    () => selectJobs(jobs, query, filter, sort),
    [jobs, query, filter, sort],
  );
  const duration = useMemo(() => totalDuration(visible), [visible]);

  const confirmDelete = useCallback(async () => {
    const job = pendingDelete;
    if (!job) return;
    try {
      await api.deleteJob(job.id);
      seqRef.current++;
      setJobs((current) => current.filter((item) => item.id !== job.id));
      toast({ title: de.toast.deleted, variant: "success" });
    } catch {
      toast({ title: de.toast.deleteFailed, variant: "destructive" });
    }
  }, [pendingDelete, toast]);

  const retry = useCallback(
    async (job: Job) => {
      try {
        const updated = await api.retryJob(job.id);
        seqRef.current++;
        setJobs((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        );
        toast({ title: de.toast.retryQueued });
      } catch {
        toast({ title: de.toast.retryFailed, variant: "destructive" });
      }
    },
    [toast],
  );

  const resetFilters = () => {
    setQuery("");
    setFilter("all");
  };

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-4 py-8">
      <section className="space-y-3">
        <h1 className="text-xl font-semibold">{de.upload.title}</h1>
        <Uploader
          onComplete={(jobId) => {
            void load();
            if (jobId) navigate(`/job/${jobId}`);
          }}
        />
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">{de.jobs.listTitle}</h2>

        {error && (
          <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <p className="text-sm text-destructive">{error}</p>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              {de.common.retry}
            </Button>
          </Card>
        )}

        {loading ? (
          <JobListSkeleton />
        ) : jobs.length === 0 ? (
          <Card>
            <EmptyState
              icon={<Inbox />}
              title={de.jobs.empty}
              description={de.jobs.emptyHint}
            />
          </Card>
        ) : (
          <>
            <JobsToolbar
              query={query}
              onQueryChange={setQuery}
              filter={filter}
              onFilterChange={setFilter}
              sort={sort}
              onSortChange={setSort}
              shown={visible.length}
              total={jobs.length}
              duration={duration}
            />

            {visible.length === 0 ? (
              <Card>
                <EmptyState
                  icon={<SearchX />}
                  title={de.jobs.searchEmpty}
                  description={de.jobs.searchEmptyHint}
                  action={
                    <Button variant="outline" size="sm" onClick={resetFilters}>
                      {de.jobs.resetFilters}
                    </Button>
                  }
                />
              </Card>
            ) : (
              <JobList
                jobs={visible}
                grouped={isDateSort(sort)}
                onDelete={setPendingDelete}
                onRetry={(job) => void retry(job)}
              />
            )}
          </>
        )}
      </section>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title={de.jobs.deleteTitle}
        description={de.jobs.deleteDescription}
        confirmLabel={de.jobs.deleteAction}
        destructive
        onConfirm={confirmDelete}
      />
    </div>
  );
}
