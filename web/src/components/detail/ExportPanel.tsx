import { useState } from "react";
import { Download, FileAudio, Loader2, SlidersHorizontal } from "lucide-react";
import { api, saveFile, type Transcript } from "@/lib/api";
import { de } from "@/i18n/de";
import {
  loadExportSettings,
  saveExportSettings,
  toExportOptions,
  type ExportSettings,
} from "@/lib/exportSettings";
import { FORMAT_LABELS } from "@/components/detail/exportLabels";
import { ExportDialog } from "@/components/detail/ExportDialog";
import { PanelHeading } from "@/components/detail/PanelHeading";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";

interface ExportPanelProps {
  jobId: string;
  doc: Transcript | null;
  hasOriginal: boolean;
}

/**
 * Two ways out: the dialog, where speakers, sections and layout are chosen,
 * and a one-click download that reuses whatever was chosen last time for the
 * whole recording. The settings are remembered in this browser.
 */
export function ExportPanel({ jobId, doc, hasOriginal }: ExportPanelProps) {
  const { toast } = useToast();
  const [settings, setSettings] = useState<ExportSettings>(loadExportSettings);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const updateSettings = (next: ExportSettings) => {
    setSettings(next);
    saveExportSettings(next);
  };

  const quickDownload = async () => {
    setBusy(true);
    try {
      saveFile(await api.exportFile(jobId, settings.format, toExportOptions(settings)));
    } catch (error) {
      toast({
        title: de.toast.exportFailed,
        description: error instanceof Error ? error.message : undefined,
        variant: "destructive",
      });
    } finally {
      setBusy(false);
    }
  };

  const quickLabel =
    settings.format === "docx" && settings.template
      ? `${FORMAT_LABELS[settings.format]} · ${de.exportMenu.withTemplate}`
      : FORMAT_LABELS[settings.format];

  return (
    <>
      <PanelHeading title={de.exportMenu.title} />
      <div className="flex flex-col gap-2">
        <Button className="justify-start" disabled={!doc} onClick={() => setOpen(true)}>
          <SlidersHorizontal />
          {de.exportMenu.configure}
        </Button>
        <p className="px-1 text-xs text-muted-foreground">{de.exportMenu.configureHint}</p>

        <Separator className="my-1" />

        <Button
          variant="outline"
          className="justify-start"
          disabled={!doc || busy}
          onClick={() => void quickDownload()}
        >
          {busy ? <Loader2 className="animate-spin" /> : <Download />}
          {de.exportMenu.quick}
        </Button>
        <p className="px-1 text-xs text-muted-foreground">
          {quickLabel}
          <br />
          {de.exportMenu.quickHint}
        </p>

        {hasOriginal && (
          <>
            <Separator className="my-1" />
            <Button
              variant="ghost"
              size="sm"
              className="justify-start"
              onClick={() => {
                // The server answers with Content-Disposition, so the page stays put.
                window.location.href = api.originalUrl(jobId);
              }}
            >
              <FileAudio />
              {de.exportMenu.original}
            </Button>
          </>
        )}
      </div>

      {open && doc && (
        <ExportDialog
          jobId={jobId}
          doc={doc}
          settings={settings}
          onSettingsChange={updateSettings}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
