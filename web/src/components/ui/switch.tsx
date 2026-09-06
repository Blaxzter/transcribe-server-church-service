import * as React from "react";
import { cn } from "@/lib/utils";

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Rendered next to the track and used as the accessible name. */
  label?: React.ReactNode;
  disabled?: boolean;
  className?: string;
  id?: string;
}

export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled,
  className,
  id,
}: SwitchProps) {
  const generatedId = React.useId();
  const labelId = `${id ?? generatedId}-label`;

  const control = (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-labelledby={label ? labelId : undefined}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-primary" : "bg-secondary border-border",
      )}
    >
      <span
        className={cn(
          "size-4 rounded-full bg-card shadow-sm transition-transform",
          checked ? "translate-x-4" : "translate-x-0.5",
        )}
      />
    </button>
  );

  if (!label) return <span className={className}>{control}</span>;

  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {control}
      <span
        id={labelId}
        onClick={() => !disabled && onCheckedChange(!checked)}
        className={cn(
          "cursor-pointer select-none text-sm text-muted-foreground",
          disabled && "cursor-not-allowed opacity-50",
        )}
      >
        {label}
      </span>
    </span>
  );
}
