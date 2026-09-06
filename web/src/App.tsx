import { Component, type ErrorInfo, type ReactNode } from "react";
import { useLayoutEffect } from "react";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
  useNavigationType,
} from "react-router-dom";
import { Mic } from "lucide-react";
import { de } from "@/i18n/de";
import { ThemeProvider } from "@/lib/theme";
import { JobsPage } from "@/pages/Jobs";
import { JobDetailPage } from "@/pages/JobDetail";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { ToastProvider } from "@/components/ui/toast";

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <BrowserRouter>
          <ScrollToTop />
          <div className="min-h-screen">
            <a
              href="#content"
              className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-sm focus:shadow-lg"
            >
              {de.nav.skipToContent}
            </a>
            <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
              <div className="mx-auto flex w-full max-w-6xl items-center gap-3 px-4 py-3">
                <Link to="/" className="flex items-center gap-2 font-semibold">
                  <Mic className="size-5 text-primary" />
                  {de.app.name}
                </Link>
                <span className="hidden text-sm text-muted-foreground sm:inline">
                  {de.app.tagline}
                </span>
                <ThemeToggle className="ml-auto" />
              </div>
            </header>
            <main id="content">
              <ErrorBoundary>
                <Routes>
                  <Route path="/" element={<JobsPage />} />
                  <Route path="/job/:id" element={<JobDetailPage />} />
                  <Route path="*" element={<JobsPage />} />
                </Routes>
              </ErrorBoundary>
            </main>
          </div>
        </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  );
}

/**
 * The recordings list scrolls the window, so without this a navigation away
 * from deep in the list would open the next page at that same offset. Back is
 * excluded: restoring the reader's place in 122 rows is the whole point of it.
 */
function ScrollToTop() {
  const { pathname } = useLocation();
  const navigationType = useNavigationType();
  useLayoutEffect(() => {
    if (navigationType !== "POP") window.scrollTo(0, 0);
  }, [pathname, navigationType]);
  return null;
}

/**
 * A render error in one page should not leave a blank document behind — the
 * data comes from a live API and the odd unexpected shape does happen.
 */
class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="mx-auto w-full max-w-md px-4 py-20 text-center">
        <p className="font-medium">{de.errors.boundaryTitle}</p>
        <p className="mt-1 text-sm text-muted-foreground">{de.errors.boundaryHint}</p>
        <Button className="mt-4" onClick={() => window.location.reload()}>
          {de.common.reload}
        </Button>
      </div>
    );
  }
}
