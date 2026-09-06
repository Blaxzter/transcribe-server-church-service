import { Check, Loader2 } from "lucide-react";
import type { Job, Stage } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

const STAGE_ORDER: Stage[] = [
  "normalize", "peaks", "music", "vad", "asr", "align", "diarize", "merge", "summarize",
];

export function ProgressPanel({ job }: { job: Job }) {
  const activeIndex = job.stage ? STAGE_ORDER.indexOf(job.stage) : -1;
  return (
    <Card>
      <CardContent className="space-y-4 pt-5">
        <div className="flex items-center gap-2">
          <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
          <p className="text-sm">
            {de.job.processing} <strong>{de.job.processingTime}</strong>
          </p>
        </div>
        <Progress value={job.progress} indeterminate={job.status === "queued"} />
        {job.message && <p className="text-sm text-muted-foreground">{job.message}</p>}
        <ol className="grid gap-1.5 sm:grid-cols-3">
          {STAGE_ORDER.map((stage, index) => (
            <li
              key={stage}
              aria-current={index === activeIndex ? "step" : undefined}
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
