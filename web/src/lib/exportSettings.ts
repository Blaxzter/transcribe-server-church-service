import type { ExportFormat, ExportOptions, ParagraphMode, SectionBreak } from "@/lib/api";

/**
 * How an export should look. Remembered per browser, because the person who
 * refines transcripts in Word wants the same shape every Sunday and should not
 * have to re-tick five switches for it.
 */
export interface ExportSettings {
  format: ExportFormat;
  /** Template id for DOCX exports; null for the built-in layout. */
  template: string | null;
  speaker_labels: boolean;
  timestamps: boolean;
  music: boolean;
  header: boolean;
  summary: boolean;
  paragraphs: ParagraphMode;
  section_break: SectionBreak;
}

/**
 * Tuned for editing in Word rather than for reading along with the audio:
 * clean prose, a new paragraph whenever someone else starts talking, a blank
 * line between the parts of the service.
 */
export const DEFAULT_EXPORT_SETTINGS: ExportSettings = {
  format: "docx",
  template: null,
  speaker_labels: false,
  timestamps: false,
  music: false,
  header: true,
  summary: false,
  paragraphs: "speaker",
  section_break: "blank",
};

export const FORMATS: ExportFormat[] = ["docx", "md", "txt", "srt", "vtt"];
export const PARAGRAPH_MODES: ParagraphMode[] = ["speaker", "blocks", "segment", "section"];
export const SECTION_BREAKS: SectionBreak[] = ["none", "blank", "heading", "page"];

const STORAGE_KEY = "transkript.export.settings";

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

export function loadExportSettings(): ExportSettings {
  let stored: Partial<Record<keyof ExportSettings, unknown>> = {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) stored = JSON.parse(raw) as typeof stored;
  } catch {
    /* private mode, blocked storage, or a corrupt entry — the defaults do */
  }
  const d = DEFAULT_EXPORT_SETTINGS;
  return {
    format: oneOf(stored.format, FORMATS, d.format),
    template: typeof stored.template === "string" ? stored.template : null,
    speaker_labels: bool(stored.speaker_labels, d.speaker_labels),
    timestamps: bool(stored.timestamps, d.timestamps),
    music: bool(stored.music, d.music),
    header: bool(stored.header, d.header),
    summary: bool(stored.summary, d.summary),
    paragraphs: oneOf(stored.paragraphs, PARAGRAPH_MODES, d.paragraphs),
    section_break: oneOf(stored.section_break, SECTION_BREAKS, d.section_break),
  };
}

export function saveExportSettings(settings: ExportSettings): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    /* nothing to do; the session still has the values in memory */
  }
}

export interface ExportSelection {
  /** null keeps every speaker. */
  speakers: string[] | null;
  /** null keeps every section. */
  sections: number[] | null;
}

/** The request body the server expects, from settings plus a selection. */
export function toExportOptions(
  settings: ExportSettings,
  selection: ExportSelection = { speakers: null, sections: null },
): ExportOptions {
  return {
    speakers: selection.speakers,
    sections: selection.sections,
    speaker_labels: settings.speaker_labels,
    timestamps: settings.timestamps,
    music: settings.music,
    header: settings.header,
    summary: settings.summary,
    paragraphs: settings.paragraphs,
    section_break: settings.section_break,
    template: settings.format === "docx" ? settings.template : null,
  };
}
