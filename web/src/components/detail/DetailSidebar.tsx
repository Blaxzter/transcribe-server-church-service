import { Download, FileText, Info, Music4, Users, type LucideIcon } from "lucide-react";
import type { Job, Transcript } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn } from "@/lib/utils";
import { DetailsPanel } from "@/components/detail/DetailsPanel";
import { ExportPanel } from "@/components/detail/ExportPanel";
import { HymnsPanel } from "@/components/detail/HymnsPanel";
import { SpeakerLegend } from "@/components/detail/SpeakerLegend";
import { SummaryPanel } from "@/components/detail/SummaryPanel";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export type DetailTab = "summary" | "speakers" | "hymns" | "export" | "details";

const TABS: Record<DetailTab, { label: string; icon: LucideIcon }> = {
  summary: { label: de.detail.tabSummary, icon: FileText },
  speakers: { label: de.detail.tabSpeakers, icon: Users },
  hymns: { label: de.detail.tabHymns, icon: Music4 },
  export: { label: de.detail.tabExport, icon: Download },
  details: { label: de.detail.tabDetails, icon: Info },
};

function availableTabs(doc: Transcript | null): DetailTab[] {
  const tabs: DetailTab[] = ["summary"];
  if (doc && Object.keys(doc.speakers).length > 0) tabs.push("speakers");
  // Legacy imports have no speakers and no summary but usually do have hymns,
  // so this is often the only tab with anything in it.
  if (doc?.hymns?.length) tabs.push("hymns");
  tabs.push("export", "details");
  return tabs;
}

/** Opens on whatever this recording actually has — legacy imports have neither. */
export function defaultDetailTab(doc: Transcript | null): DetailTab {
  if (!doc) return "summary";
  if (doc.summary) return "summary";
  if (Object.keys(doc.speakers).length > 0) return "speakers";
  return doc.hymns?.length ? "hymns" : "export";
}

interface DetailSidebarProps {
  job: Job;
  doc: Transcript | null;
  legacy: boolean;
  value: DetailTab;
  onValueChange: (tab: DetailTab) => void;
  onSeek?: (seconds: number) => void;
  className?: string;
}

/**
 * Summary, speakers, export and metadata share one column as tabs. Stacking
 * them made a long summary push the legend and the export buttons off-screen;
 * as tabs the column keeps the height of the transcript next to it and each
 * panel scrolls on its own.
 */
export function DetailSidebar({
  job,
  doc,
  legacy,
  value,
  onValueChange,
  onSeek,
  className,
}: DetailSidebarProps) {
  const tabs = availableTabs(doc);
  const active = tabs.includes(value) ? value : tabs[0];

  return (
    <Card className={cn("flex flex-col overflow-hidden", className)}>
      <Tabs
        value={active}
        onValueChange={(next) => onValueChange(next as DetailTab)}
        className="min-h-0 flex-1"
      >
        <div className="border-b border-border p-2">
          {/* The open tab spells itself out and the rest stay icons, which is
              how four of them fit this column. A hover bubble is no use here —
              the pane clips its own overflow — so the icons carry a native
              title instead. */}
          <TabsList className="w-full">
            {tabs.map((key) => {
              const { label, icon: Icon } = TABS[key];
              const current = key === active;
              return (
                <TabsTrigger
                  key={key}
                  value={key}
                  aria-label={label}
                  title={label}
                  className={current ? "flex-1" : "flex-none"}
                >
                  <Icon />
                  {current && <span className="min-w-0 truncate">{label}</span>}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </div>

        <TabsContent value="summary" className="min-h-0 flex-1 overflow-y-auto p-5">
          <SummaryPanel doc={doc} legacy={legacy} />
        </TabsContent>
        <TabsContent value="speakers" className="min-h-0 flex-1 overflow-y-auto p-5">
          <SpeakerLegend doc={doc} />
        </TabsContent>
        <TabsContent value="hymns" className="min-h-0 flex-1 overflow-y-auto p-5">
          <HymnsPanel hymns={doc?.hymns ?? []} onSeek={onSeek} />
        </TabsContent>
        <TabsContent value="export" className="min-h-0 flex-1 overflow-y-auto p-5">
          <ExportPanel jobId={job.id} doc={doc} hasOriginal={job.has_original} />
        </TabsContent>
        <TabsContent value="details" className="min-h-0 flex-1 overflow-y-auto p-5">
          <DetailsPanel job={job} doc={doc} legacy={legacy} />
        </TabsContent>
      </Tabs>
    </Card>
  );
}
