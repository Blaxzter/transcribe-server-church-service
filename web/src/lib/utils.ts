import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { de } from "@/i18n/de";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** 3725 -> "1:02:05"; 125 -> "2:05" */
export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => n.toString().padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** Human duration for lists: "1 Std 32 Min" */
export function formatDuration(seconds: number | null): string {
  if (!seconds) return "—";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} ${de.units.minuteShort}`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest
    ? `${hours} ${de.units.hourShort} ${rest} ${de.units.minuteShort}`
    : `${hours} ${de.units.hourShort}`;
}

export function formatBytes(bytes: number | null): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

export function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // `service_date` is a bare calendar date, which the spec parses as UTC
  // midnight while every consumer reads it back in local time — a day off for
  // anyone west of Greenwich. Build it as a local date instead.
  const dateOnly = DATE_ONLY.exec(iso);
  if (dateOnly) {
    const [, year, month, day] = dateOnly;
    const local = new Date(Number(year), Number(month) - 1, Number(day));
    // Out-of-range parts silently roll over here, where `new Date(iso)` used to
    // yield Invalid Date; keep returning null for those.
    return local.getMonth() === Number(month) - 1 ? local : null;
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(iso: string | null): string {
  const date = toDate(iso);
  if (!date) return "—";
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** "18.08.2023" */
export function formatDate(iso: string | null): string {
  const date = toDate(iso);
  if (!date) return "—";
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

/** "1 Aufnahme" / "122 Aufnahmen" */
export function formatCount(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * The date a recording should be sorted and grouped by: the service it belongs
 * to, falling back to the upload timestamp for jobs that never got one.
 */
export function jobDate(job: {
  service_date: string | null;
  created_at: string;
}): Date | null {
  return toDate(job.service_date) ?? toDate(job.created_at);
}

export type TimeBucket =
  | "today"
  | "yesterday"
  | "thisWeek"
  | "lastWeek"
  | "thisMonth"
  | "month"
  | "year"
  | "unknown";

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** Monday-based, as German calendars are. */
function startOfWeek(date: Date): Date {
  const start = startOfDay(date);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return start;
}

/** Shifts a day boundary by whole calendar days, which DST makes uneven. */
function addDays(date: Date, days: number): Date {
  const shifted = new Date(date);
  shifted.setDate(shifted.getDate() + days);
  return shifted;
}

/**
 * Coarser the older it gets: day, then week, then month, then year. That keeps
 * a list of a hundred-odd recordings navigable without a date picker.
 */
export function timeBucket(date: Date | null, now: Date = new Date()): TimeBucket {
  if (!date) return "unknown";
  const day = startOfDay(date).getTime();
  const today = startOfDay(now);
  if (day >= today.getTime()) return "today";
  if (day >= addDays(today, -1).getTime()) return "yesterday";

  const weekStart = startOfWeek(now);
  if (day >= weekStart.getTime()) return "thisWeek";
  if (day >= addDays(weekStart, -7).getTime()) return "lastWeek";

  if (date.getFullYear() === now.getFullYear()) {
    return date.getMonth() === now.getMonth() ? "thisMonth" : "month";
  }
  return "year";
}

/** Stable key for a bucket, so two different months never collapse into one. */
export function timeBucketKey(date: Date | null, now: Date = new Date()): string {
  const bucket = timeBucket(date, now);
  if (!date) return bucket;
  if (bucket === "month") return `month:${date.getFullYear()}-${date.getMonth()}`;
  if (bucket === "year") return `year:${date.getFullYear()}`;
  return bucket;
}

export function timeBucketLabel(date: Date | null, now: Date = new Date()): string {
  const bucket = timeBucket(date, now);
  switch (bucket) {
    case "today":
      return de.time.today;
    case "yesterday":
      return de.time.yesterday;
    case "thisWeek":
      return de.time.thisWeek;
    case "lastWeek":
      return de.time.lastWeek;
    case "thisMonth":
      return de.time.thisMonth;
    case "month":
      return date
        ? new Intl.DateTimeFormat("de-DE", { month: "long" }).format(date)
        : de.time.earlier;
    case "year":
      return date ? String(date.getFullYear()) : de.time.earlier;
    default:
      return de.time.unknownDate;
  }
}

export interface TimeGroup<T> {
  key: string;
  label: string;
  items: T[];
}

/**
 * Groups an already-sorted list into age buckets. Input order is preserved and
 * each bucket is opened once, so the caller sorts first and gets headings in
 * exactly that order.
 */
export function groupByTime<T>(
  items: T[],
  getDate: (item: T) => Date | null,
  now: Date = new Date(),
): TimeGroup<T>[] {
  const groups: TimeGroup<T>[] = [];
  const byKey = new Map<string, TimeGroup<T>>();
  for (const item of items) {
    const date = getDate(item);
    const key = timeBucketKey(date, now);
    let group = byKey.get(key);
    if (!group) {
      group = { key, label: timeBucketLabel(date, now), items: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.items.push(item);
  }
  return groups;
}

/** "#3b82f6" + 0.1 -> "rgb(59 130 246 / 0.1)"; other formats pass through. */
export function withAlpha(color: string, alpha: number): string {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (!match) return color;
  const value = match[1];
  const full =
    value.length === 3
      ? value
          .split("")
          .map((char) => char + char)
          .join("")
      : value;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgb(${r} ${g} ${b} / ${clamp(alpha, 0, 1)})`;
}
