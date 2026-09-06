import { cn } from "@/lib/utils";

interface ProgressProps {
  /** 0..1 */
  value: number;
  className?: string;
  indeterminate?: boolean;
}

export const Progress = ({ value, className, indeterminate }: ProgressProps) => (
  <div
    role="progressbar"
    aria-valuemin={0}
    aria-valuemax={100}
    aria-valuenow={indeterminate ? undefined : Math.round(value * 100)}
    className={cn(
      "relative h-2 w-full overflow-hidden rounded-full bg-secondary",
      className,
    )}
  >
    <div
      className={cn(
        "h-full rounded-full bg-primary transition-[width] duration-500 ease-out",
        indeterminate && "animate-soft-pulse",
      )}
      style={{ width: `${Math.min(Math.max(value, 0), 1) * 100}%` }}
    />
  </div>
);
