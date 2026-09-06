import { Download, FileAudio } from "lucide-react";
import { api } from "@/lib/api";
import { de } from "@/i18n/de";
import { PanelHeading } from "@/components/detail/PanelHeading";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";

const FORMATS: { format: string; label: string }[] = [
  { format: "docx", label: de.exportMenu.docx },
  { format: "md", label: de.exportMenu.md },
  { format: "txt", label: de.exportMenu.txt },
  { format: "srt", label: de.exportMenu.srt },
  { format: "vtt", label: de.exportMenu.vtt },
];

interface ExportPanelProps {
  jobId: string;
  hasOriginal: boolean;
}

export function ExportPanel({ jobId, hasOriginal }: ExportPanelProps) {
  const { toast } = useToast();

  // The server answers with Content-Disposition, so the page stays where it is.
  const download = (url: string) => {
    window.location.href = url;
  };

  const exportAs = (format: string) => {
    toast({ title: de.toast.exportStarted });
    download(api.exportUrl(jobId, format));
  };

  return (
    <>
      <PanelHeading title={de.exportMenu.title} />
      <div className="flex flex-col gap-2">
        {FORMATS.map((entry) => (
          <Button
            key={entry.format}
            variant="outline"
            size="sm"
            className="justify-start"
            onClick={() => exportAs(entry.format)}
          >
            <Download />
            {entry.label}
          </Button>
        ))}
        {hasOriginal && (
          <>
            <Separator className="my-1" />
            <Button
              variant="ghost"
              size="sm"
              className="justify-start"
              onClick={() => download(api.originalUrl(jobId))}
            >
              <FileAudio />
              {de.exportMenu.original}
            </Button>
          </>
        )}
      </div>
    </>
  );
}
