import type {
  ExportFormat,
  ExportOptions,
  MusicStyle,
  ParagraphMode,
  SectionBreak,
  SpeakerStyle,
} from "@/lib/api";

/**
 * How an export should look. Remembered per browser, because the person who
 * refines transcripts in Word wants the same shape every Sunday and should not
 * have to re-tick five switches for it.
 */
export interface ExportSettings {
  format: ExportFormat;
  /** Template id for DOCX exports; null for the built-in layout. */
  template: string | null;
  /** Uploaded font for the built-in layout; null for the Word default. */
  font: string | null;
  speaker_labels: boolean;
  timestamps: boolean;
  music: boolean;
  header: boolean;
  summary: boolean;
  paragraphs: ParagraphMode;
  section_break: SectionBreak;
  speaker_style: SpeakerStyle;
  blank_lines: boolean;
  music_style: MusicStyle;
  /**
   * Where and when the service was held. Not in the recording and not in the
   * database, so they are typed here and only ever reach a template's {{Ort}}
   * and {{Zeit}}. Remembered because next Sunday is usually the same church at
   * the same hour.
   */
  location: string;
  service_time: string;
}

/**
 * Tuned for editing in Word rather than for reading along with the audio: the
 * shape of the service protocols the church already writes by hand. Clean
 * prose in short paragraphs with a blank line between them, the speaker named
 * once on a line of their own when they take over, and every piece of music a
 * line waiting to be turned into "Chorlied Nr. 33: „Danket dem Herrn“".
 *
 * Short paragraphs rather than one per speaker: a sermon is a single turn, and
 * as one paragraph it runs for pages.
 */
export const DEFAULT_EXPORT_SETTINGS: ExportSettings = {
  format: "docx",
  template: null,
  font: null,
  // Both were once off because they were noise to delete in Word: the name
  // sat in front of every paragraph and the music read "[Gemeindegesang]".
  // With the styles below they are the two things the protocol is built from.
  speaker_labels: true,
  timestamps: false,
  music: true,
  header: true,
  summary: false,
  paragraphs: "blocks",
  section_break: "blank",
  speaker_style: "line",
  blank_lines: true,
  music_style: "cue",
  location: "",
  service_time: "",
};

export const FORMATS: ExportFormat[] = ["docx", "md", "txt", "srt", "vtt"];
export const PARAGRAPH_MODES: ParagraphMode[] = ["speaker", "blocks", "segment", "section"];
export const SECTION_BREAKS: SectionBreak[] = ["none", "blank", "heading", "page"];
export const SPEAKER_STYLES: SpeakerStyle[] = ["line", "inline"];
export const MUSIC_STYLES: MusicStyle[] = ["cue", "marker"];

const STORAGE_KEY = "transkript.export.settings";

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback;
}

function bool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function text(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
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
    font: typeof stored.font === "string" ? stored.font : null,
    speaker_labels: bool(stored.speaker_labels, d.speaker_labels),
    timestamps: bool(stored.timestamps, d.timestamps),
    music: bool(stored.music, d.music),
    header: bool(stored.header, d.header),
    summary: bool(stored.summary, d.summary),
    paragraphs: oneOf(stored.paragraphs, PARAGRAPH_MODES, d.paragraphs),
    section_break: oneOf(stored.section_break, SECTION_BREAKS, d.section_break),
    speaker_style: oneOf(stored.speaker_style, SPEAKER_STYLES, d.speaker_style),
    blank_lines: bool(stored.blank_lines, d.blank_lines),
    music_style: oneOf(stored.music_style, MUSIC_STYLES, d.music_style),
    location: text(stored.location, d.location),
    service_time: text(stored.service_time, d.service_time),
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
  const template = settings.format === "docx" ? settings.template : null;
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
    speaker_style: settings.speaker_style,
    blank_lines: settings.blank_lines,
    music_style: settings.music_style,
    location: settings.location,
    service_time: settings.service_time,
    template,
    // A template brings its own fonts, and the server only applies the picked
    // one to the built-in layout; sending it anyway would be a lie to the UI.
    font: settings.format === "docx" && !template ? settings.font : null,
  };
}

// --- the places services are held ------------------------------------------
// A congregation records in a handful of the same buildings, so the place is
// offered as a list to pick from rather than typed out every Sunday. Kept
// apart from the settings above: those are one remembered value each, this is
// everything that has ever been used.
const LOCATIONS_KEY = "transkript.export.locations";
const MAX_LOCATIONS = 12;

export function loadLocations(): string[] {
  try {
    const raw = window.localStorage.getItem(LOCATIONS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((entry): entry is string => typeof entry === "string");
  } catch {
    return [];
  }
}

/** Put a place at the front of the list, without duplicating it. */
export function rememberLocation(location: string): string[] {
  const name = location.trim();
  if (!name) return loadLocations();
  const kept = loadLocations().filter(
    (entry) => entry.toLocaleLowerCase() !== name.toLocaleLowerCase(),
  );
  const list = [name, ...kept].slice(0, MAX_LOCATIONS);
  try {
    window.localStorage.setItem(LOCATIONS_KEY, JSON.stringify(list));
  } catch {
    /* the list is a convenience; losing it costs one retyped word */
  }
  return list;
}
