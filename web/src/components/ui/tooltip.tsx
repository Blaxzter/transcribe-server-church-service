import * as React from "react";
import { cn } from "@/lib/utils";

const SIDES = {
  top: "bottom-[calc(100%+0.35rem)] left-1/2 -translate-x-1/2",
  bottom: "top-[calc(100%+0.35rem)] left-1/2 -translate-x-1/2",
  left: "right-[calc(100%+0.35rem)] top-1/2 -translate-y-1/2",
  right: "left-[calc(100%+0.35rem)] top-1/2 -translate-y-1/2",
} as const;

export interface TooltipProps {
  label: React.ReactNode;
  children: React.ReactNode;
  side?: keyof typeof SIDES;
  className?: string;
}

/**
 * Hover/focus label. CSS only — the wrapped control keeps its own aria-label,
 * so nothing here needs to reach the accessibility tree.
 */
export function Tooltip({ label, children, side = "top", className }: TooltipProps) {
  return (
    <span className={cn("group/tooltip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        aria-hidden
        className={cn(
          "pointer-events-none absolute z-50 whitespace-nowrap rounded-md border border-border bg-popover px-2 py-1 text-xs text-popover-foreground opacity-0 shadow-md transition-opacity duration-150",
          "group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100",
          SIDES[side],
        )}
      >
        {label}
      </span>
    </span>
  );
}
