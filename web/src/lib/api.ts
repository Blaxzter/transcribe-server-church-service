/** Typed client for the Transkript API. Same origin in every environment. */

export type JobStatus = "queued" | "running" | "done" | "failed" | "canceled";

export type Stage =
  | "normalize" | "peaks" | "music" | "vad"
  | "asr" | "align" | "diarize" | "merge" | "summarize";

export interface Job {
  id: string;
  title: string;
  service_date: string | null;
  original_filename: string;
  size_bytes: number | null;
  duration_s: number | null;
  status: JobStatus;
  stage: Stage | null;
  progress: number;
  message: string | null;
  error: string | null;
  speaker_count: number | null;
  created_at: string;
  finished_at: string | null;
  has_audio: boolean;
  has_peaks: boolean;
  has_transcript: boolean;
  has_summary: boolean;
  /** Absent on API builds older than the legacy-badge change. */
  has_music?: boolean;
  has_original: boolean;
}

export interface Word {
  word: string;
  start: number;
  end: number;
  probability?: number;
}

export interface Segment {
  id: string;
  type: "speech" | "music";
  start: number;
  end: number;
  text: string;
  speaker?: string | null;
  marker?: string;
  words?: Word[] | null;
  edited?: boolean;
}

export interface Speaker {
  label: string;
  color: string;
  auto?: boolean;
}

export interface Hymn {
  number: number;
  /** Seconds into the recording, or null when only the filename knew about it. */
  at: number | null;
  segment_id: string | null;
  context: string | null;
  mentions: number;
  source: "transcript" | "title" | "both";
}

export interface Transcript {
  version: number;
  job_id: string;
  duration: number;
  language: string;
  speakers: Record<string, Speaker>;
  segments: Segment[];
  summary?: string | null;
  outline?: string[] | null;
  /** "legacy-import" means no speakers, music markers or summary. */
  source?: string | null;
  hymns?: Hymn[];
  updated_at?: string;
}

export interface Peaks {
  version: number;
  duration: number;
  pixels_per_second: number;
  bits: number;
  data: number[];
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const api = {
  listJobs: () => request<{ jobs: Job[]; stages: Stage[] }>("/api/jobs"),

  getJob: (id: string) => request<Job>(`/api/jobs/${id}`),

  patchJob: (id: string, body: { title?: string; service_date?: string | null }) =>
    request<Job>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),

  deleteJob: (id: string) =>
    request<{ status: string }>(`/api/jobs/${id}`, { method: "DELETE" }),

  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),

  getTranscript: (id: string) => request<Transcript>(`/api/jobs/${id}/transcript`),

  patchTranscript: (
    id: string,
    body: {
      segments?: { id: string; text?: string; speaker?: string }[];
      speakers?: Record<string, { label: string }>;
    },
  ) =>
    request<Transcript>(`/api/jobs/${id}/transcript`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  getPeaks: (id: string) => request<Peaks>(`/api/jobs/${id}/peaks`),

  audioUrl: (id: string) => `/api/jobs/${id}/audio`,

  originalUrl: (id: string) => `/api/jobs/${id}/original`,

  exportUrl: (id: string, format: string) => `/api/jobs/${id}/export/${format}`,
};

/**
 * Subscribe to a job's progress. Returns an unsubscribe function.
 *
 * EventSource reconnects on its own, which matters here: the tunnel will drop
 * an idle stream and the server-side keepalive comment is not always enough.
 */
export function subscribeToJob(
  id: string,
  onEvent: (event: Partial<Job>) => void,
): () => void {
  const source = new EventSource(`/api/jobs/${id}/events`);
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as Partial<Job>);
    } catch {
      /* keepalive or malformed frame */
    }
  };
  source.onerror = () => {
    // Leave reconnection to EventSource; only a terminal state closes it.
  };
  return () => source.close();
}
