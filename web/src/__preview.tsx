/*
 * Renders the export dialog on its own against a stubbed API, so the layout
 * can be looked at without a backend. Built by scripts/preview-dialog.mjs into
 * one self-contained HTML file. Not part of the app.
 */
import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import type { Transcript } from "@/lib/api";
import { ExportDialog } from "@/components/detail/ExportDialog";
import { ToastProvider } from "@/components/ui/toast";
import { ThemeProvider } from "@/lib/theme";
import { DEFAULT_EXPORT_SETTINGS, type ExportSettings } from "@/lib/exportSettings";
import { DOCX_BASE64 } from "./__preview_docx";
import "./index.css";

const SPEAKERS = [
  ["S0", "Daniel Stolpe", "#2563eb"],
  ["S1", "Sprecher 2", "#db2777"],
  ["S2", "Sprecher 3", "#16a34a"],
  ["S3", "Sprecher 4", "#ea580c"],
  ["S4", "Sprecher 5", "#9333ea"],
  ["S5", "Sprecher 6", "#0d9488"],
  ["S6", "Sprecher 7", "#dc2626"],
] as const;

const doc: Transcript = {
  version: 1,
  job_id: "j1",
  duration: 4200,
  language: "de",
  speakers: Object.fromEntries(
    SPEAKERS.map(([id, label, color]) => [id, { label, color }]),
  ),
  segments: [],
  summary: "Jugendgottesdienst mit Predigt über Jesaja 43.",
};

const SECTIONS = [
  {
    index: 0, start: 237, end: 364, words: 290, segment_count: 12,
    speakers: { S0: 120 },
    music: [{ text: "[Orgelspiel]", start: 0 }],
    preview: "Wir dürfen zusammenkommen zu unserem Jugendgottesdienst und wir dü…",
  },
  {
    index: 1, start: 707, end: 1732, words: 1931, segment_count: 96,
    speakers: { S1: 400, S0: 300, S2: 120, S3: 60 },
    music: [{ text: "[Musik]", start: 400 }, { text: "[Orgelspiel]", start: 600 }],
    preview: "des Vaters, Gottes des Sohnes und Gottes des Heiligen Geistes. Amen. Ihr Li…",
  },
  {
    index: 2, start: 1872, end: 1890, words: 35, segment_count: 3,
    speakers: { S0: 18 },
    music: [{ text: "[Musik]", start: 1800 }],
    preview: "Es gibt Kirchen, da wird geklatscht nach so einem Gesang. Wir dürfen das a…",
  },
  {
    index: 3, start: 2140, end: 2960, words: 1204, segment_count: 61,
    speakers: { S4: 500, S0: 200, S5: 90 },
    music: [{ text: "[Gemeindegesang]", start: 2000 }],
    preview: "Und dann kam dieser eine Satz, der mich seitdem nicht mehr loslässt: Fürc…",
  },
];

const FONTS = [
  {
    id: "f1", name: "Predigtschrift", family: "Source Serif 4",
    filename: "SourceSerif4-Regular.ttf", size_bytes: 284_120,
    created_at: "2026-09-06T10:00:00Z", updated_at: "2026-09-06T10:00:00Z",
  },
  {
    id: "f2", name: "Gemeindebrief", family: "Lato",
    filename: "Lato-Regular.ttf", size_bytes: 120_400,
    created_at: "2026-09-06T10:00:00Z", updated_at: "2026-09-06T10:00:00Z",
  },
];

const TEMPLATES = [
  {
    id: "t1", name: "Predigt", filename: "Predigt.docx", size_bytes: 24_100,
    placeholders: ["titel", "datum", "text"], unknown_placeholders: [],
    created_at: "2026-09-06T10:00:00Z", updated_at: "2026-09-06T10:00:00Z",
  },
];

const docxBytes = Uint8Array.from(atob(DOCX_BASE64), (c) => c.charCodeAt(0));

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

// Every call the dialog makes, answered from the fixtures above.
window.fetch = async (input: RequestInfo | URL): Promise<Response> => {
  const url = String(typeof input === "string" || input instanceof URL ? input : input.url);
  if (url.includes("/sections")) return json({ sections: SECTIONS });
  if (url.includes("/api/templates")) {
    return json({
      templates: TEMPLATES,
      fields: ["titel", "datum", "dauer", "sprecher", "lieder", "liederliste",
               "zusammenfassung", "text"],
    });
  }
  if (url.includes("/api/fonts")) return json({ fonts: FONTS });
  if (url.includes("/export/")) {
    // A little latency, so the "rebuilding" state is visible too.
    await new Promise((resolve) => setTimeout(resolve, 250));
    return new Response(docxBytes, {
      status: 200,
      headers: {
        "Content-Type":
          "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "Content-Disposition": 'attachment; filename="Gottesdienst.docx"',
      },
    });
  }
  return json({});
};

// Pinned, so the harness shows the same thing wherever it is opened. Add
// ?theme=dark to look at the other one.
try {
  const asked = new URLSearchParams(window.location.search).get("theme");
  window.localStorage.setItem("transkript-theme", asked === "dark" ? "dark" : "light");
} catch {
  /* storage blocked */
}

function Harness() {
  const [settings, setSettings] = useState<ExportSettings>(DEFAULT_EXPORT_SETTINGS);
  return (
    <ThemeProvider>
      <ToastProvider>
        <div className="min-h-screen bg-background" />
        <ExportDialog
          jobId="j1"
          doc={doc}
          settings={settings}
          onSettingsChange={setSettings}
          onClose={() => undefined}
        />
      </ToastProvider>
    </ThemeProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Harness />
  </StrictMode>,
);
