import { useEffect, useState } from "react";
import type { Job, JobStatus } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export type SaveState = "idle" | "saving" | "saved" | "error";

const STATUS_VARIANT: Record<JobStatus, BadgeProps["variant"]> = {
  queued: "default",
  running: "info",
  done: "success",
  failed: "destructive",
  canceled: "outline",
};

const SAVE_TEXT: Record<SaveState, string> = {
  idle: "",
  saving: de.job.saving,
  saved: de.job.saved,
  error: de.job.saveFailed,
};

interface JobHeaderProps {
  job: Job;
  legacy: boolean;
  saveState: SaveState;
  onSave: (title: string, serviceDate: string | null) => void;
}

/** Title and service date are edited in place; both commit on blur. */
export function JobHeader({ job, legacy, saveState, onSave }: JobHeaderProps) {
  const [title, setTitle] = useState(job.title);
  const [serviceDate, setServiceDate] = useState(job.service_date ?? "");

  useEffect(() => {
    setTitle(job.title);
    setServiceDate(job.service_date ?? "");
  }, [job.id, job.title, job.service_date]);

  const commit = () => {
    const trimmed = title.trim();
    if (!trimmed) {
      setTitle(job.title);
      return;
    }
    if (trimmed !== job.title || (serviceDate || null) !== job.service_date) {
      onSave(trimmed, serviceDate || null);
    }
  };

  return (
    <Card>
      <CardContent className="flex flex-wrap items-center gap-x-3 gap-y-2 p-3">
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
          aria-label={de.job.titleLabel}
          placeholder={de.job.titlePlaceholder}
          variant="ghost"
          inputSize="lg"
          className="min-w-0 flex-1 basis-64 text-lg font-semibold"
        />
        <Input
          type="date"
          value={serviceDate}
          onChange={(event) => setServiceDate(event.target.value)}
          onBlur={commit}
          aria-label={de.job.dateLabel}
          inputSize="lg"
          className="w-44"
        />
        <Badge variant={STATUS_VARIANT[job.status]}>{de.status[job.status]}</Badge>
        {legacy && <Badge variant="outline">{de.jobs.legacy}</Badge>}
        <span
          aria-live="polite"
          className={cn(
            "w-44 shrink-0 text-right text-xs text-muted-foreground transition-opacity",
            saveState === "idle" && "opacity-0",
            saveState === "error" && "text-destructive",
          )}
        >
          {SAVE_TEXT[saveState]}
        </span>
      </CardContent>
    </Card>
  );
}
