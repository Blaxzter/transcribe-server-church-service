import type { ExportFormat, ParagraphMode, SectionBreak } from "@/lib/api";
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

/** "titel" -> "{{Titel}}", the way it is typed into the template. */
export function placeholderToken(name: string): string {
  return `{{${name.charAt(0).toUpperCase()}${name.slice(1)}}}`;
}
