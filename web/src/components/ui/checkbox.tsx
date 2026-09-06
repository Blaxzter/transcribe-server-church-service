import * as React from "react";
import { cn } from "@/lib/utils";

export interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Rendered next to the box and used as the accessible name. */
  label?: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  className?: string;
  id?: string;
}

/**
 * Native checkbox with the theme's accent — a real checkbox, so it works with
 * the keyboard and screen readers without any extra wiring.
 */
export function Checkbox({
  checked,
  onCheckedChange,
  label,
  description,
  disabled,
  className,
  id,
}: CheckboxProps) {
  const generatedId = React.useId();
  const inputId = id ?? generatedId;

  const input = (
    <input
      type="checkbox"
      id={inputId}
      checked={checked}
      disabled={disabled}
      onChange={(event) => onCheckedChange(event.target.checked)}
      className={cn(
        "mt-0.5 size-4 shrink-0 cursor-pointer rounded border-input accent-primary",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "disabled:cursor-not-allowed disabled:opacity-50",
      )}
    />
  );

  if (!label) return <span className={className}>{input}</span>;

  return (
    <label
      htmlFor={inputId}
      className={cn(
        "flex cursor-pointer select-none items-start gap-2.5 text-sm",
        disabled && "cursor-not-allowed opacity-60",
        className,
      )}
    >
      {input}
      <span className="min-w-0 flex-1">
        <span className="block">{label}</span>
        {description && (
          <span className="block text-xs text-muted-foreground">{description}</span>
        )}
      </span>
    </label>
  );
}
