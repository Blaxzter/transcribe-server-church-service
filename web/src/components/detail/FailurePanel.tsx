import { useState } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import type { Job } from "@/lib/api";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";

interface FailurePanelProps {
  job: Job;
  onRetry: () => Promise<void>;
}

export function FailurePanel({ job, onRetry }: FailurePanelProps) {
  const [confirming, setConfirming] = useState(false);
  return (
    <Card className="border-destructive/40">
      <CardContent className="space-y-3 pt-5">
        <div className="flex items-center gap-2 font-medium text-destructive">
          <AlertCircle className="size-4 shrink-0" />
          {de.job.failedTitle}
        </div>
        {job.error && (
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
            {job.error}
          </pre>
        )}
        <Button variant="outline" onClick={() => setConfirming(true)}>
          <RefreshCw />
          {de.jobs.retry}
        </Button>
      </CardContent>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={de.jobs.retryTitle}
        description={de.jobs.retryDescription}
        confirmLabel={de.jobs.retryAction}
        onConfirm={onRetry}
      />
    </Card>
  );
}
