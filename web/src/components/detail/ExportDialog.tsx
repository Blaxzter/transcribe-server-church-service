import { useEffect, useMemo, useState } from "react";
import { Download, Loader2, Music, Settings2, Type } from "lucide-react";
import {
  api,
  saveFile,
  type ExportFormat,
  type Font,
  type ParagraphMode,
  type Section,
  type SectionBreak,
  type Template,
  type Transcript,
} from "@/lib/api";
import { de } from "@/i18n/de";
import { cn, formatTime, withAlpha } from "@/lib/utils";
import {
  DEFAULT_EXPORT_SETTINGS,
  FORMATS,
  PARAGRAPH_MODES,
  SECTION_BREAKS,
  toExportOptions,
  type ExportSettings,
} from "@/lib/exportSettings";
import {
  FORMAT_LABELS,
  PARAGRAPH_LABELS,
  SECTION_BREAK_LABELS,
} from "@/components/detail/exportLabels";
import { ExportPreview, type Preview } from "@/components/detail/ExportPreview";
import { FontManager } from "@/components/detail/FontManager";
import { TemplateManager } from "@/components/detail/TemplateManager";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

const PREVIEW_DEBOUNCE_MS = 400;

interface ExportDialogProps {
  jobId: string;
  doc: Transcript;
  settings: ExportSettings;
  onSettingsChange: (settings: ExportSettings) => void;
  onClose: () => void;
}

/** The sub-view that has taken over the dialog, if any. */
type Managing = "templates" | "fonts" | null;

/**
 * Everything about one export in one place: what goes in (speakers, sections
 * of the service) and how it is laid out on the left, the page it produces on
 * the right. The layout settings persist; the selection is per recording and
 * starts with everything ticked.
 */
export function ExportDialog({
  jobId,
  doc,
  settings,
  onSettingsChange,
  onClose,
}: ExportDialogProps) {
  const { toast } = useToast();
  const speakerIds = useMemo(() => Object.keys(doc.speakers), [doc.speakers]);
  const [selectedSpeakers, setSelectedSpeakers] = useState<Set<string>>(
    () => new Set(speakerIds),
  );
  const [sections, setSections] = useState<Section[] | null>(null);
  const [sectionsError, setSectionsError] = useState(false);
  const [selectedSections, setSelectedSections] = useState<Set<number> | null>(null);
  const [templates, setTemplates] = useState<Template[] | null>(null);
  const [fonts, setFonts] = useState<Font[] | null>(null);
  const [fields, setFields] = useState<string[]>([]);
  const [managing, setManaging] = useState<Managing>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [building, setBuilding] = useState(true);
  const [downloading, setDownloading] = useState(false);

  // --- data ---------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    api
      .getSections(jobId)
      .then((value) => {
        if (cancelled) return;
        setSections(value.sections);
        setSelectedSections(new Set(value.sections.map((section) => section.index)));
      })
      .catch(() => !cancelled && setSectionsError(true));
    api
      .listTemplates()
      .then((value) => {
        if (cancelled) return;
        setTemplates(value.templates);
        setFields(value.fields);
      })
      .catch(() => !cancelled && setTemplates([]));
    api
      .listFonts()
      .then((value) => !cancelled && setFonts(value.fonts))
      .catch(() => !cancelled && setFonts([]));
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Something deleted on another day must not haunt the stored settings.
  const templateMissing =
    settings.template !== null &&
    templates !== null &&
    !templates.some((template) => template.id === settings.template);
  const fontMissing =
    settings.font !== null &&
    fonts !== null &&
    !fonts.some((font) => font.id === settings.font);

  const update = (patch: Partial<ExportSettings>) =>
    onSettingsChange({ ...settings, ...patch });

  // --- selection -> request -------------------------------------------------
  const allSpeakers = selectedSpeakers.size === speakerIds.length;
  const allSections =
    sections === null || selectedSections === null || selectedSections.size === sections.length;

  const options = useMemo(
    () =>
      toExportOptions(
        {
          ...settings,
          template: templateMissing ? null : settings.template,
          font: fontMissing ? null : settings.font,
        },
        {
          speakers: allSpeakers ? null : [...selectedSpeakers],
          sections: allSections ? null : [...(selectedSections ?? [])],
        },
      ),
    [
      settings, templateMissing, fontMissing,
      allSpeakers, selectedSpeakers, allSections, selectedSections,
    ],
  );
  const format = settings.format;
  const isDocx = format === "docx";
  const isSubtitles = format === "srt" || format === "vtt";
  const usingTemplate = isDocx && options.template != null;

  // --- preview ------------------------------------------------------------
  const requestKey = JSON.stringify([format, options]);
  useEffect(() => {
    let cancelled = false;
    setBuilding(true);
    const timer = window.setTimeout(async () => {
      try {
        const file = await api.exportFile(jobId, format, options);
        if (cancelled) return;
        if (format === "docx") {
          setPreview({ kind: "docx", blob: file.blob });
        } else {
          setPreview({ kind: "text", text: await file.blob.text() });
        }
      } catch (error) {
        if (!cancelled) {
          setPreview({
            kind: "error",
            message: error instanceof Error ? error.message : undefined,
          });
        }
      } finally {
        if (!cancelled) setBuilding(false);
      }
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // `options` is captured through requestKey, which is what actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, requestKey]);

  // --- download -----------------------------------------------------------
  const download = async () => {
    setDownloading(true);
    try {
      saveFile(await api.exportFile(jobId, format, options));
      onClose();
    } catch (error) {
      toast({
        title: de.toast.exportFailed,
        description: error instanceof Error ? error.message : undefined,
        variant: "destructive",
      });
    } finally {
      setDownloading(false);
    }
  };

  const toggleSpeaker = (id: string, checked: boolean) =>
    setSelectedSpeakers((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });

  const toggleSection = (index: number, checked: boolean) =>
    setSelectedSections((current) => {
      const next = new Set(current ?? []);
      if (checked) next.add(index);
      else next.delete(index);
      return next;
    });

  const nothingSelected =
    (speakerIds.length > 0 && selectedSpeakers.size === 0 && !settings.music) ||
    (selectedSections !== null && selectedSections.size === 0);

  const title =
    managing === "templates"
      ? de.templates.title
      : managing === "fonts"
        ? de.fonts.title
        : de.exportDialog.title;

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !downloading && onClose()}
      title={title}
      description={managing ? undefined : de.exportDialog.description}
      // The two-card layout owns the height: each card scrolls on its own, so
      // a long section list never pushes the preview out of sight.
      size={managing ? "lg" : "2xl"}
      className={
        managing
          ? undefined
          : "flex h-[calc(100vh-2rem)] flex-col overflow-y-hidden bg-muted/60"
      }
      bodyClassName={managing ? undefined : "flex min-h-0 flex-1 flex-col overflow-y-auto"}
      footer={
        managing ? undefined : (
          <>
            <span className="mr-auto self-center text-xs text-muted-foreground">
              {speakerIds.length > 0 && (
                <>
                  {selectedSpeakers.size} {de.common.of} {speakerIds.length}{" "}
                  {de.exportDialog.selectionSpeakers}
                </>
              )}
              {speakerIds.length > 0 && sections && " · "}
              {sections && (
                <>
                  {selectedSections?.size ?? sections.length} {de.common.of} {sections.length}{" "}
                  {de.exportDialog.selectionSections}
                </>
              )}
            </span>
            <Button variant="ghost" disabled={downloading} onClick={onClose}>
              {de.common.cancel}
            </Button>
            <Button disabled={downloading || nothingSelected} onClick={() => void download()}>
              {downloading ? <Loader2 className="animate-spin" /> : <Download />}
              {downloading ? de.exportDialog.downloading : de.exportDialog.download}
            </Button>
          </>
        )
      }
    >
      {managing === "templates" ? (
        <TemplateManager
          templates={templates ?? []}
          fields={fields}
          onTemplatesChange={setTemplates}
          onBack={() => setManaging(null)}
        />
      ) : managing === "fonts" ? (
        <FontManager
          fonts={fonts ?? []}
          onFontsChange={setFonts}
          onBack={() => setManaging(null)}
        />
      ) : (
        <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-2">
          {/* ---------------------------------------------------- options */}
          <Card className="min-h-0 space-y-6 overflow-y-auto p-5">
            <Group title={de.exportDialog.format}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Labelled label={de.exportDialog.format}>
                  <Select
                    value={format}
                    onChange={(event) => update({ format: event.target.value as ExportFormat })}
                  >
                    {FORMATS.map((entry) => (
                      <option key={entry} value={entry}>
                        {FORMAT_LABELS[entry]}
                      </option>
                    ))}
                  </Select>
                </Labelled>
                <Labelled label={de.exportDialog.template}>
                  <Select
                    value={templateMissing ? "" : (settings.template ?? "")}
                    disabled={!isDocx || templates === null}
                    title={isDocx ? undefined : de.exportDialog.templatesOnlyDocx}
                    onChange={(event) => update({ template: event.target.value || null })}
                  >
                    <option value="">{de.exportDialog.noTemplate}</option>
                    {(templates ?? []).map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </Select>
                </Labelled>
                <Labelled label={de.exportDialog.font}>
                  <Select
                    value={fontMissing ? "" : (settings.font ?? "")}
                    disabled={!isDocx || usingTemplate || fonts === null}
                    title={usingTemplate ? de.exportDialog.fontsOnlyPlain : undefined}
                    onChange={(event) => update({ font: event.target.value || null })}
                  >
                    <option value="">{de.exportDialog.noFont}</option>
                    {(fonts ?? []).map((font) => (
                      <option key={font.id} value={font.id}>
                        {font.name}
                      </option>
                    ))}
                  </Select>
                </Labelled>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
                <Button
                  variant="link"
                  size="xs"
                  className="h-auto px-0"
                  onClick={() => setManaging("templates")}
                >
                  <Settings2 />
                  {de.exportDialog.manageTemplates}
                </Button>
                <Button
                  variant="link"
                  size="xs"
                  className="h-auto px-0"
                  onClick={() => setManaging("fonts")}
                >
                  <Type />
                  {de.exportDialog.manageFonts}
                </Button>
                {templateMissing && isDocx && (
                  <span className="text-xs text-warning">{de.exportDialog.templateMissing}</span>
                )}
                {fontMissing && isDocx && !usingTemplate && (
                  <span className="text-xs text-warning">{de.exportDialog.fontMissing}</span>
                )}
              </div>
              {usingTemplate ? (
                <p className="mt-2 text-xs text-muted-foreground">
                  {de.exportDialog.templateNote}
                </p>
              ) : (
                options.font != null && (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {de.exportDialog.fontNote}
                  </p>
                )
              )}
            </Group>

            {speakerIds.length > 0 && (
              <Group
                title={de.exportDialog.speakers}
                hint={de.exportDialog.speakersHint}
                actions={
                  <AllNone
                    onAll={() => setSelectedSpeakers(new Set(speakerIds))}
                    onNone={() => setSelectedSpeakers(new Set())}
                  />
                }
              >
                <ul className="grid gap-1.5 sm:grid-cols-2">
                  {speakerIds.map((id) => {
                    const speaker = doc.speakers[id];
                    return (
                      <li key={id}>
                        <Checkbox
                          checked={selectedSpeakers.has(id)}
                          onCheckedChange={(checked) => toggleSpeaker(id, checked)}
                          className="rounded-md px-2 py-1.5 hover:bg-accent/60"
                          label={
                            <span className="inline-flex items-center gap-2">
                              <span
                                className="size-2.5 shrink-0 rounded-full"
                                style={{ background: speaker.color }}
                              />
                              <span className="truncate">{speaker.label}</span>
                            </span>
                          }
                        />
                      </li>
                    );
                  })}
                </ul>
              </Group>
            )}

            <Group
              title={de.exportDialog.sections}
              hint={de.exportDialog.sectionsHint}
              actions={
                sections && sections.length > 1 ? (
                  <AllNone
                    onAll={() =>
                      setSelectedSections(new Set(sections.map((section) => section.index)))
                    }
                    onNone={() => setSelectedSections(new Set())}
                  />
                ) : undefined
              }
            >
              {sectionsError ? (
                <p className="text-sm text-destructive">{de.errors.loadFailed}</p>
              ) : sections === null ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="size-4 animate-spin" />
                  {de.exportDialog.sectionsLoading}
                </p>
              ) : sections.length === 0 ? (
                <p className="text-sm text-muted-foreground">{de.exportDialog.sectionsEmpty}</p>
              ) : (
                <ul className="space-y-1.5">
                  {sections.map((section) => (
                    <SectionRow
                      key={section.index}
                      section={section}
                      doc={doc}
                      checked={selectedSections?.has(section.index) ?? true}
                      muted={
                        Object.keys(section.speakers).length > 0 &&
                        !Object.keys(section.speakers).some((id) => selectedSpeakers.has(id))
                      }
                      onCheckedChange={(checked) => toggleSection(section.index, checked)}
                    />
                  ))}
                </ul>
              )}
            </Group>

            <Group
              title={de.exportDialog.layout}
              actions={
                <Button
                  variant="link"
                  size="xs"
                  className="h-auto px-0 text-muted-foreground"
                  onClick={() =>
                    update({
                      ...DEFAULT_EXPORT_SETTINGS,
                      format: settings.format,
                      template: settings.template,
                      font: settings.font,
                    })
                  }
                >
                  {de.exportDialog.resetLayout}
                </Button>
              }
            >
              <div className="grid gap-x-4 gap-y-2.5 sm:grid-cols-2">
                <Switch
                  checked={settings.speaker_labels}
                  onCheckedChange={(checked) => update({ speaker_labels: checked })}
                  label={de.exportDialog.speakerLabels}
                />
                <Switch
                  checked={settings.timestamps}
                  onCheckedChange={(checked) => update({ timestamps: checked })}
                  disabled={isSubtitles}
                  label={de.exportDialog.timestamps}
                />
                <Switch
                  checked={settings.music}
                  onCheckedChange={(checked) => update({ music: checked })}
                  label={de.exportDialog.music}
                />
                <Switch
                  checked={settings.header}
                  onCheckedChange={(checked) => update({ header: checked })}
                  disabled={isSubtitles || usingTemplate}
                  label={de.exportDialog.header}
                />
                <Switch
                  checked={settings.summary}
                  onCheckedChange={(checked) => update({ summary: checked })}
                  disabled={isSubtitles || usingTemplate || !doc.summary}
                  label={de.exportDialog.summary}
                />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Labelled label={de.exportDialog.paragraphs}>
                  <Select
                    value={settings.paragraphs}
                    disabled={isSubtitles}
                    onChange={(event) =>
                      update({ paragraphs: event.target.value as ParagraphMode })
                    }
                  >
                    {PARAGRAPH_MODES.map((mode) => (
                      <option key={mode} value={mode}>
                        {PARAGRAPH_LABELS[mode]}
                      </option>
                    ))}
                  </Select>
                </Labelled>
                <Labelled label={de.exportDialog.sectionBreak}>
                  <Select
                    value={settings.section_break}
                    disabled={isSubtitles}
                    onChange={(event) =>
                      update({ section_break: event.target.value as SectionBreak })
                    }
                  >
                    {SECTION_BREAKS.map((mode) => (
                      <option key={mode} value={mode}>
                        {SECTION_BREAK_LABELS[mode]}
                      </option>
                    ))}
                  </Select>
                </Labelled>
              </div>
            </Group>
          </Card>

          {/* ---------------------------------------------------- preview */}
          <Card
            className="flex min-h-0 flex-col gap-3 overflow-hidden p-5"
            aria-busy={building}
          >
            <div className="flex items-baseline gap-2">
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold">{de.exportDialog.preview}</h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {isDocx ? de.exportDialog.previewNote : de.exportDialog.previewNoteText}
                </p>
              </div>
              {building && preview !== null && (
                <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
              )}
            </div>
            {/* Rebuilding keeps the last page on screen, only dimmed: it is the
                same document with one switch flipped, and blanking the panel
                on every click made the dialog feel like it was reloading. */}
            <div
              className={cn(
                "flex min-h-0 flex-1 flex-col transition-opacity",
                building && preview !== null && "opacity-50",
              )}
            >
              <ExportPreview preview={preview} />
            </div>
          </Card>
        </div>
      )}
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
function Group({
  title,
  hint,
  actions,
  children,
}: {
  title: string;
  hint?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex min-h-6 items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {actions}
      </div>
      {hint && <p className="-mt-1 mb-2 text-xs text-muted-foreground">{hint}</p>}
      {children}
    </section>
  );
}

function Labelled({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function AllNone({ onAll, onNone }: { onAll: () => void; onNone: () => void }) {
  return (
    <span className="flex items-center gap-1 text-xs">
      <Button variant="ghost" size="xs" onClick={onAll}>
        {de.exportDialog.all}
      </Button>
      <Button variant="ghost" size="xs" onClick={onNone}>
        {de.exportDialog.none}
      </Button>
    </span>
  );
}

function SectionRow({
  section,
  doc,
  checked,
  muted,
  onCheckedChange,
}: {
  section: Section;
  doc: Transcript;
  checked: boolean;
  /** Ticked, but none of its speakers are — it would export as nothing. */
  muted: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const speakers = Object.entries(section.speakers)
    .sort((a, b) => b[1] - a[1])
    .map(([id]) => doc.speakers[id])
    .filter(Boolean);
  return (
    <li>
      <label
        className={cn(
          "flex cursor-pointer gap-2.5 rounded-md border px-3 py-2 transition-colors",
          checked ? "border-border bg-card" : "border-transparent",
          "hover:bg-accent/60",
          muted && checked && "opacity-60",
        )}
      >
        <Checkbox checked={checked} onCheckedChange={onCheckedChange} className="pt-0.5" />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2 text-sm">
            <span className="font-medium">
              {de.exportDialog.section} {section.index + 1}
            </span>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {formatTime(section.start)} – {formatTime(section.end)}
            </span>
            <span className="ml-auto shrink-0 text-xs tabular-nums text-muted-foreground">
              {section.words} {de.exportDialog.words}
            </span>
          </span>
          {section.music.length > 0 && (
            <span className="mt-0.5 flex items-center gap-1 text-xs italic text-muted-foreground">
              <Music className="size-3 shrink-0" />
              <span className="truncate">{section.music.map((m) => m.text).join(", ")}</span>
            </span>
          )}
          {section.preview && (
            <span className="mt-0.5 block truncate text-xs text-muted-foreground">
              {section.preview}
            </span>
          )}
          {speakers.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1">
              {speakers.map((speaker) => (
                <span
                  key={speaker.label}
                  className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium"
                  style={{ color: speaker.color, background: withAlpha(speaker.color, 0.12) }}
                >
                  <span className="size-1.5 rounded-full" style={{ background: speaker.color }} />
                  {speaker.label}
                </span>
              ))}
            </span>
          )}
        </span>
      </label>
    </li>
  );
}
