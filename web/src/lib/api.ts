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
  /** Seconds into the recording. Every hymn reported was actually announced. */
  at: number;
  segment_id: string;
  context: string;
  mentions: number;
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

export type ExportFormat = "docx" | "md" | "txt" | "srt" | "vtt";
export type ParagraphMode = "blocks" | "segment" | "speaker" | "section";
export type SectionBreak = "none" | "blank" | "heading" | "page";

/** Mirrors `ExportOptions` on the server; every field is optional there too. */
export interface ExportOptions {
  /** Speaker ids to keep; omit for all, empty for none. */
  speakers?: string[] | null;
  /** Section indices to keep; omit for all. */
  sections?: number[] | null;
  speaker_labels?: boolean;
  timestamps?: boolean;
  music?: boolean;
  header?: boolean;
  summary?: boolean;
  paragraphs?: ParagraphMode;
  section_break?: SectionBreak;
  /** Template id; DOCX only. */
  template?: string | null;
  /** Font id; DOCX without a template only. */
  font?: string | null;
}

/** A run of speech between two pieces of music, as the export picker shows it. */
export interface Section {
  index: number;
  start: number;
  end: number;
  /** Seconds each speaker talks in this section. */
  speakers: Record<string, number>;
  segment_count: number;
  words: number;
  /** Music markers that lead into this section (or close the last one). */
  music: { text: string; start: number }[];
  preview: string;
}

export interface Template {
  id: string;
  name: string;
  filename: string;
  size_bytes: number | null;
  /** Lower-cased placeholder names found in the document, in order. */
  placeholders: string[];
  /** Placeholders the export does not know and will leave untouched. */
  unknown_placeholders: string[];
  created_at: string;
  updated_at: string;
}

export interface Font {
  id: string;
  /** What the user called it; the family is what the document asks Word for. */
  name: string;
  family: string;
  filename: string;
  size_bytes: number | null;
  created_at: string;
  updated_at: string;
}

export interface TemplateList {
  templates: Template[];
  /** Placeholder names the export can fill. */
  fields: string[];
}

export interface ExportFile {
  blob: Blob;
  filename: string;
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

/** The server's `detail` for a failed response, or the bare status text. */
async function failure(response: Response): Promise<ApiError> {
  let detail = response.statusText;
  try {
    detail = (await response.json())?.detail ?? detail;
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(response.status, detail);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) throw await failure(response);
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

  getSections: (id: string) => request<{ sections: Section[] }>(`/api/jobs/${id}/sections`),

  /**
   * An export with options is a POST, so the file arrives as a blob and the
   * caller hands it to the browser as a download. The server names the file.
   */
  exportFile: async (id: string, format: ExportFormat, options: ExportOptions) => {
    const response = await fetch(`/api/jobs/${id}/export/${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
    });
    if (!response.ok) throw await failure(response);
    const disposition = response.headers.get("Content-Disposition") ?? "";
    const match = /filename="([^"]+)"/.exec(disposition);
    return {
      blob: await response.blob(),
      filename: match?.[1] ?? `transkript.${format}`,
    } satisfies ExportFile;
  },

  listTemplates: () => request<TemplateList>("/api/templates"),

  uploadTemplate: (file: File, name?: string) =>
    upload<Template>("/api/templates", file, name),

  renameTemplate: (id: string, name: string) =>
    request<Template>(`/api/templates/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),

  deleteTemplate: (id: string) =>
    request<{ status: string }>(`/api/templates/${id}`, { method: "DELETE" }),

  templateFileUrl: (id: string) => `/api/templates/${id}/file`,

  listFonts: () => request<{ fonts: Font[] }>("/api/fonts"),

  uploadFont: (file: File, name?: string) => upload<Font>("/api/fonts", file, name),

  renameFont: (id: string, name: string) =>
    request<Font>(`/api/fonts/${id}`, { method: "PATCH", body: JSON.stringify({ name }) }),

  deleteFont: (id: string) =>
    request<{ status: string }>(`/api/fonts/${id}`, { method: "DELETE" }),

  fontFileUrl: (id: string) => `/api/fonts/${id}/file`,
};

/** A multipart POST; `request` cannot do these, it sets a JSON content type. */
async function upload<T>(path: string, file: File, name?: string): Promise<T> {
  const body = new FormData();
  body.append("file", file, file.name);
  if (name) body.append("name", name);
  const response = await fetch(path, { method: "POST", body });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

/** Hands a blob to the browser as a download and cleans up after itself. */
export function saveFile({ blob, filename }: ExportFile): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking synchronously can cancel the download in some browsers.
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

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
