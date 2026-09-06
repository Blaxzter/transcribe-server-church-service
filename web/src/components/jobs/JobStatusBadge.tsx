import { AlertCircle, Clock, Loader2 } from "lucide-react";
import type { JobStatus } from "@/lib/api";
import { de } from "@/i18n/de";
import { Badge } from "@/components/ui/badge";

/**
 * Status chip for a recording row. `done` is the norm and stays quiet, so the
 * type excludes it rather than trusting every caller to guard.
 */
export function JobStatusBadge({ status }: { status: Exclude<JobStatus, "done"> }) {
  switch (status) {
    case "failed":
    case "canceled":
      return (
        <Badge variant="destructive">
          <AlertCircle />
          {de.status[status]}
        </Badge>
      );
    case "running":
      return (
        <Badge variant="info">
          <Loader2 className="animate-spin" />
          {de.status.running}
        </Badge>
      );
    default:
      return (
        <Badge>
          <Clock />
          {de.status.queued}
        </Badge>
      );
  }
}
