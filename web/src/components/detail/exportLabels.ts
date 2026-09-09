import type {
  ExportFormat,
  MusicStyle,
  ParagraphMode,
  SectionBreak,
  SpeakerStyle,
} from "@/lib/api";
import { de } from "@/i18n/de";

export const FORMAT_LABELS: Record<ExportFormat, string> = {
  docx: de.exportMenu.docx,
  md: de.exportMenu.md,
  txt: de.exportMenu.txt,
  srt: de.exportMenu.srt,
  vtt: de.exportMenu.vtt,
};

export const PARAGRAPH_LABELS: Record<ParagraphMode, string> = {
  speaker: de.exportDialog.paragraphsSpeaker,
  blocks: de.exportDialog.paragraphsBlocks,
  segment: de.exportDialog.paragraphsSegment,
  section: de.exportDialog.paragraphsSection,
};

export const SECTION_BREAK_LABELS: Record<SectionBreak, string> = {
  none: de.exportDialog.sectionBreakNone,
  blank: de.exportDialog.sectionBreakBlank,
  heading: de.exportDialog.sectionBreakHeading,
  page: de.exportDialog.sectionBreakPage,
};

export const SPEAKER_STYLE_LABELS: Record<SpeakerStyle, string> = {
  line: de.exportDialog.speakerStyleLine,
  inline: de.exportDialog.speakerStyleInline,
};

export const MUSIC_STYLE_LABELS: Record<MusicStyle, string> = {
  cue: de.exportDialog.musicStyleCue,
  marker: de.exportDialog.musicStyleMarker,
};

/**
 * How a placeholder is spelled where capitalising the first letter is not
 * enough. Matching in the template is case-insensitive either way; this is
 * only so the name shown to copy reads the way a German word does.
 */
const SPELLINGS: Record<string, string> = {
  langesdatum: "LangesDatum",
  liederliste: "Liederliste",
};

/** "titel" -> "{{Titel}}", the way it is typed into the template. */
export function placeholderToken(name: string): string {
  const spelled = SPELLINGS[name] ?? name.charAt(0).toUpperCase() + name.slice(1);
  return `{{${spelled}}}`;
}
