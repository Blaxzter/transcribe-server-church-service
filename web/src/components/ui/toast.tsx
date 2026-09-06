import * as React from "react";
import { createPortal } from "react-dom";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { de } from "@/i18n/de";

export type ToastVariant = "default" | "success" | "destructive";

export interface ToastOptions {
  title: string;
  description?: string;
  variant?: ToastVariant;
  /** Milliseconds until it disappears; 0 keeps it until dismissed. */
  duration?: number;
}

interface ToastEntry extends ToastOptions {
  id: number;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => number;
  dismiss: (id: number) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION = 4000;

const ICONS: Record<ToastVariant, typeof Info> = {
  default: Info,
  success: CheckCircle2,
  destructive: AlertCircle,
};

const ACCENTS: Record<ToastVariant, string> = {
  default: "text-muted-foreground",
  success: "text-success",
  destructive: "text-destructive",
};

/** Mounted once in App; every component reaches it through useToast(). */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<ToastEntry[]>([]);
  const timers = React.useRef(new Map<number, number>());
  const nextId = React.useRef(0);

  const dismiss = React.useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) window.clearTimeout(timer);
    timers.current.delete(id);
    setToasts((current) => current.filter((entry) => entry.id !== id));
  }, []);

  const toast = React.useCallback(
    (options: ToastOptions) => {
      const id = (nextId.current += 1);
      setToasts((current) => [...current, { ...options, id }]);
      const duration = options.duration ?? DEFAULT_DURATION;
      if (duration > 0) {
        timers.current.set(id, window.setTimeout(() => dismiss(id), duration));
      }
      return id;
    },
    [dismiss],
  );

  React.useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((timer) => window.clearTimeout(timer));
  }, []);

  const value = React.useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end">
          {toasts.map((entry) => {
            const variant = entry.variant ?? "default";
            const Icon = ICONS[variant];
            return (
              <div
                key={entry.id}
                role={variant === "destructive" ? "alert" : "status"}
                aria-live={variant === "destructive" ? "assertive" : "polite"}
                className="pointer-events-auto flex w-full max-w-sm animate-toast-in items-start gap-3 rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-lg"
              >
                <Icon className={cn("mt-0.5 size-4 shrink-0", ACCENTS[variant])} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{entry.title}</p>
                  {entry.description && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {entry.description}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  aria-label={de.common.dismiss}
                  onClick={() => dismiss(entry.id)}
                  className="rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <X className="size-4" />
                </button>
              </div>
            );
          })}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = React.useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}
