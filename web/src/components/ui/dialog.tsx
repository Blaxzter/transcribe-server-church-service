import * as React from "react";
import { createPortal } from "react-dom";
import { Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

const SIZES = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-5xl",
} as const;

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: React.ReactNode;
  /** Right-aligned action row; usually two Buttons. */
  footer?: React.ReactNode;
  size?: keyof typeof SIZES;
  hideClose?: boolean;
  className?: string;
  initialFocusRef?: React.RefObject<HTMLElement>;
}

/**
 * Modal dialog: portal, focus trap, Escape and backdrop to close, focus
 * restored to whatever opened it. This is what replaces window.confirm.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "sm",
  hideClose,
  className,
  initialFocusRef,
}: DialogProps) {
  const panelRef = React.useRef<HTMLDivElement>(null);
  const titleId = React.useId();
  const descriptionId = React.useId();

  // Every caller passes a freshly allocated inline arrow. Keeping it in a ref
  // lets the effect below depend on `open` alone — otherwise it tore down and
  // re-armed on each render of the owner, stealing focus back to the initial
  // element on every poll tick and every keystroke.
  const onOpenChangeRef = React.useRef(onOpenChange);
  onOpenChangeRef.current = onOpenChange;

  React.useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const panel = panelRef.current;
    const initial =
      initialFocusRef?.current ?? panel?.querySelector<HTMLElement>(FOCUSABLE) ?? panel;
    initial?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onOpenChangeRef.current(false);
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const items = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((element) => element.offsetParent !== null);
      if (!items.length) {
        event.preventDefault();
        panelRef.current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === panelRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = previousOverflow;
      // The opener is often a row button that the confirmed action removes;
      // focusing a detached node silently drops the user at <body>.
      if (opener?.isConnected) opener.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        aria-hidden
        onClick={() => onOpenChange(false)}
        className="absolute inset-0 animate-fade-in bg-overlay backdrop-blur-[2px]"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "relative max-h-[calc(100vh-2rem)] w-full animate-panel-in overflow-y-auto rounded-xl border border-border bg-popover p-5 text-popover-foreground shadow-xl outline-none",
          SIZES[size],
          className,
        )}
      >
        <h2 id={titleId} className="pr-8 text-base font-semibold">
          {title}
        </h2>
        {description && (
          <p id={descriptionId} className="mt-1.5 text-sm text-muted-foreground">
            {description}
          </p>
        )}
        {!hideClose && (
          <Button
            variant="ghost"
            size="icon"
            className="absolute right-3 top-3 text-muted-foreground"
            aria-label={de.a11y.closeDialog}
            onClick={() => onOpenChange(false)}
          >
            <X />
          </Button>
        )}
        {children && <div className="mt-4">{children}</div>}
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  /** Force the pending state; an async onConfirm sets it on its own. */
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
}

/** Yes/no dialog. Stays open and shows a spinner while onConfirm is pending. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = de.common.confirm,
  cancelLabel = de.common.cancel,
  destructive,
  busy,
  onConfirm,
}: ConfirmDialogProps) {
  const [pending, setPending] = React.useState(false);
  const confirmRef = React.useRef<HTMLButtonElement>(null);
  const working = busy || pending;

  React.useEffect(() => {
    if (!open) setPending(false);
  }, [open]);

  const confirm = async () => {
    setPending(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => !working && onOpenChange(next)}
      title={title}
      description={description}
      initialFocusRef={confirmRef}
      footer={
        <>
          <Button
            variant="ghost"
            disabled={working}
            onClick={() => onOpenChange(false)}
          >
            {cancelLabel}
          </Button>
          <Button
            ref={confirmRef}
            variant={destructive ? "destructive" : "default"}
            disabled={working}
            onClick={() => void confirm()}
          >
            {working && <Loader2 className="animate-spin" />}
            {confirmLabel}
          </Button>
        </>
      }
    />
  );
}
