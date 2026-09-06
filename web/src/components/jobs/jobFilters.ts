import type { Job } from "@/lib/api";
import { de } from "@/i18n/de";
import { formatDate, jobDate } from "@/lib/utils";

export type JobFilter = "all" | "done" | "active" | "failed";
export type JobSort = "newest" | "oldest" | "title" | "longest";

export const JOB_FILTERS: { value: JobFilter; label: string }[] = [
  { value: "all", label: de.jobs.filterAll },
  { value: "done", label: de.jobs.filterDone },
  { value: "active", label: de.jobs.filterActive },
  { value: "failed", label: de.jobs.filterFailed },
];

export const JOB_SORTS: { value: JobSort; label: string }[] = [
  { value: "newest", label: de.jobs.sortNewest },
  { value: "oldest", label: de.jobs.sortOldest },
  { value: "title", label: de.jobs.sortTitle },
  { value: "longest", label: de.jobs.sortLongest },
];

/** Date headings only make sense while the list is actually in date order. */
export function isDateSort(sort: JobSort): boolean {
  return sort === "newest" || sort === "oldest";
}

export function isActive(job: Job): boolean {
  return job.status === "queued" || job.status === "running";
}

/**
 * Legacy imports were taken over from the old system as finished text only.
 * The authoritative marker lives in transcript.json, which the list endpoint
 * does not read, so the list goes by music.json instead: the music stage
 * always writes it, and only a processed job has ever run that stage.
 *
 * Tested against false rather than for falsiness on purpose: an API that
 * predates the field sends nothing, and no badge beats badging all of them.
 */
export function isLegacy(job: Job): boolean {
  return job.status === "done" && job.has_music === false;
}

function matchesFilter(job: Job, filter: JobFilter): boolean {
  switch (filter) {
    case "done":
      return job.status === "done";
    case "active":
      return isActive(job);
    case "failed":
      return job.status === "failed" || job.status === "canceled";
    default:
      return true;
  }
}

/**
 * Everything a row shows should also be findable: title, source file and the
 * service date in both the German and the ISO spelling, so "08.2023" and
 * "2023-08" both hit.
 */
function haystack(job: Job): string {
  const iso = job.service_date ?? job.created_at;
  return [job.title, job.original_filename, formatDate(iso), iso]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

/** All terms must match, in any order — "2026 ostern" finds the service. */
function matchesQuery(job: Job, terms: string[]): boolean {
  if (!terms.length) return true;
  const text = haystack(job);
  return terms.every((term) => text.includes(term));
}

function compare(a: Job, b: Job, sort: JobSort): number {
  switch (sort) {
    case "title":
      return (a.title || de.jobs.untitled).localeCompare(
        b.title || de.jobs.untitled,
        "de-DE",
        { numeric: true },
      );
    case "longest":
      return (b.duration_s ?? 0) - (a.duration_s ?? 0);
    default: {
      // Undated jobs sink to the bottom in both directions.
      const left = jobDate(a)?.getTime();
      const right = jobDate(b)?.getTime();
      if (left === undefined) return right === undefined ? 0 : 1;
      if (right === undefined) return -1;
      return sort === "oldest" ? left - right : right - left;
    }
  }
}

export function selectJobs(
  jobs: Job[],
  query: string,
  filter: JobFilter,
  sort: JobSort,
): Job[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return jobs
    .filter((job) => matchesFilter(job, filter) && matchesQuery(job, terms))
    .sort((a, b) => compare(a, b, sort));
}

export function totalDuration(jobs: Job[]): number {
  return jobs.reduce((sum, job) => sum + (job.duration_s ?? 0), 0);
}
