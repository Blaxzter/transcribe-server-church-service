import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Download, Loader2, Music, Settings2 } from "lucide-react";
import {
  api,
  saveFile,
  type ExportFormat,
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
import { TemplateManager } from "@/components/detail/TemplateManager";
import { Button } from "@/components/ui/button";
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

type Preview =
  | { kind: "loading" }
  | { kind: "text"; text: string }
  | { kind: "docx"; blob: Blob }
  | { kind: "error"; message?: string };

/**
 * Everything about one export in one place: what goes in (speakers, sections
 * of the service), how it is laid out, which Word template to pour it into —
 * next to a live preview of the result. The layout settings persist; the
 * selection is per recording and starts with everything ticked.
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
  const [fields, setFields] = useState<string[]>([]);
  const [managing, setManaging] = useState(false);
  const [preview, setPreview] = useState<Preview>({ kind: "loading" });
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
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // A template that was deleted on another day must not haunt the settings.
  const templateMissing =
    settings.template !== null &&
    templates !== null &&
    !templates.some((template) => template.id === settings.template);

  const update = (patch: Partial<ExportSettings>) =>
    onSettingsChange({ ...settings, ...patch });

  // --- selection -> request -------------------------------------------------
  const allSpeakers = selectedSpeakers.size === speakerIds.length;
  const allSections =
    sections === null || selectedSections === null || selectedSections.size === sections.length;

  const options = useMemo(
    () =>
      toExportOptions(
        { ...settings, template: templateMissing ? null : settings.template },
        {
          speakers: allSpeakers ? null : [...selectedSpeakers],
          sections: allSections ? null : [...(selectedSections ?? [])],
        },
      ),
    [settings, templateMissing, allSpeakers, selectedSpeakers, allSections, selectedSections],
  );
  const format = settings.format;
  const isDocx = format === "docx";
  const isSubtitles = format === "srt" || format === "vtt";
  const usingTemplate = isDocx && options.template != null;

  // --- preview ------------------------------------------------------------
  const requestKey = JSON.stringify([format, options]);
  useEffect(() => {
    let cancelled = false;
    setPreview({ kind: "loading" });
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

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !downloading && onClose()}
      title={managing ? de.templates.title : de.exportDialog.title}
      description={managing ? undefined : de.exportDialog.description}
      size="xl"
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
      {managing ? (
        <TemplateManager
          templates={templates ?? []}
          fields={fields}
          onTemplatesChange={setTemplates}
          onBack={() => setManaging(false)}
        />
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {/* ---------------------------------------------------- options */}
          <div className="space-y-6">
            <Group title={de.exportDialog.format}>
              <div className="grid gap-2 sm:grid-cols-2">
                <Select
                  value={format}
                  aria-label={de.exportDialog.format}
                  onChange={(event) => update({ format: event.target.value as ExportFormat })}
                >
                  {FORMATS.map((entry) => (
                    <option key={entry} value={entry}>
                      {FORMAT_LABELS[entry]}
                    </option>
                  ))}
                </Select>
                <Select
                  value={templateMissing ? "" : (settings.template ?? "")}
                  aria-label={de.exportDialog.template}
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
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                <Button
                  variant="link"
                  size="xs"
                  className="h-auto px-0"
                  onClick={() => setManaging(true)}
                >
                  <Settings2 />
                  {de.exportDialog.manageTemplates}
                </Button>
                {templateMissing && isDocx && (
                  <span className="text-xs text-warning">{de.exportDialog.templateMissing}</span>
                )}
              </div>
              {usingTemplate && (
                <p className="mt-2 text-xs text-muted-foreground">{de.exportDialog.templateNote}</p>
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
                <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
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
          </div>

          {/* ---------------------------------------------------- preview */}
          <div className="min-w-0 md:sticky md:top-0 md:self-start">
            <Group title={de.exportDialog.preview} hint={de.exportDialog.previewNote}>
              <div
                className={cn(
                  "relative max-h-[60vh] min-h-40 overflow-auto rounded-md border border-border bg-muted/40",
                  preview.kind === "loading" && "opacity-60",
                )}
                aria-busy={preview.kind === "loading"}
              >
                <PreviewBody preview={preview} />
              </div>
            </Group>
          </div>
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

function PreviewBody({ preview }: { preview: Preview }) {
  if (preview.kind === "error") {
    return (
      <p className="flex items-center gap-2 p-4 text-sm text-destructive">
        <AlertCircle className="size-4 shrink-0" />
        {preview.message ?? de.exportDialog.previewFailed}
      </p>
    );
  }
  if (preview.kind === "loading") {
    return (
      <p className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        {de.exportDialog.previewLoading}
      </p>
    );
  }
  if (preview.kind === "text") {
    if (!preview.text.trim()) {
      return <p className="p-4 text-sm text-muted-foreground">{de.exportDialog.previewEmpty}</p>;
    }
    return (
      <pre className="whitespace-pre-wrap break-words p-4 font-mono text-xs leading-relaxed">
        {preview.text}
      </pre>
    );
  }
  return <DocxPreview blob={preview.blob} />;
}

/**
 * Renders the actual .docx the server produced, so a template's own layout is
 * what the preview shows. The renderer is loaded on first use; most visits to
 * the page never open this dialog.
 */
function DocxPreview({ blob }: { blob: Blob }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let cancelled = false;
    setFailed(false);
    import("docx-preview")
      .then(({ renderAsync }) => {
        if (cancelled) return;
        host.replaceChildren();
        return renderAsync(blob, host, undefined, {
          inWrapper: false,
          ignoreWidth: true,
          ignoreHeight: true,
          ignoreLastRenderedPageBreak: true,
          breakPages: false,
          useBase64URL: true,
        });
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [blob]);

  if (failed) {
    return <p className="p-4 text-sm text-destructive">{de.exportDialog.previewFailed}</p>;
  }
  // Paper stays white in the dark theme too: it is a preview of a printed page.
  return (
    <div
      ref={hostRef}
      className="docx-preview m-3 rounded-sm bg-white p-5 text-neutral-900 shadow-sm [&_p]:mb-2 [&_p]:text-[13px] [&_p]:leading-relaxed"
    />
  );
}
