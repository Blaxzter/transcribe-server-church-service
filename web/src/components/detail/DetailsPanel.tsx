import type { ReactNode } from "react";
import type { Job, Transcript } from "@/lib/api";
import { de } from "@/i18n/de";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/utils";
import { PanelHeading } from "@/components/detail/PanelHeading";

interface DetailsPanelProps {
  job: Job;
  doc: Transcript | null;
  legacy: boolean;
}

export function DetailsPanel({ job, doc, legacy }: DetailsPanelProps) {
  const speakerCount = doc ? Object.keys(doc.speakers).length : (job.speaker_count ?? 0);
  return (
    <>
      <PanelHeading title={de.detail.tabDetails} />
      <dl className="divide-y divide-border text-sm">
        <Row label={de.job.file} value={job.original_filename} />
        <Row label={de.job.size} value={formatBytes(job.size_bytes)} />
        <Row label={de.jobs.duration} value={formatDuration(job.duration_s)} />
        <Row label={de.jobs.created} value={formatDateTime(job.created_at)} />
        {job.finished_at && (
          <Row label={de.job.finished} value={formatDateTime(job.finished_at)} />
        )}
        {doc && <Row label={de.job.language} value={doc.language.toUpperCase()} />}
        {doc && <Row label={de.job.segments} value={doc.segments.length} />}
        {speakerCount > 0 && <Row label={de.jobs.speakers} value={speakerCount} />}
      </dl>
      {legacy && (
        <p className="mt-4 text-xs text-muted-foreground">{de.transcript.imported}</p>
      )}
    </>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2">
      <dt className="shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-right">{value}</dd>
    </div>
  );
}
