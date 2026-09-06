import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Mic } from "lucide-react";
import { de } from "@/i18n/de";
import { JobsPage } from "@/pages/Jobs";
import { JobDetailPage } from "@/pages/JobDetail";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen">
        <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
          <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3">
            <Link to="/" className="flex items-center gap-2 font-semibold">
              <Mic className="size-5 text-primary" />
              {de.app.name}
            </Link>
            <span className="text-sm text-muted-foreground">
              {de.app.tagline}
            </span>
          </div>
        </header>
        <main>
          <Routes>
            <Route path="/" element={<JobsPage />} />
            <Route path="/job/:id" element={<JobDetailPage />} />
            <Route path="*" element={<JobsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
