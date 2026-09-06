import type { ReactNode } from "react";

/**
 * Names the active sidebar panel and carries its actions. The tab bar only
 * labels the tab that is open — it has to fit four of them into a narrow
 * column — so the heading is what names the panel below it.
 */
export function PanelHeading({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-3 flex min-h-8 items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </div>
  );
}
