import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const inputVariants = cva(
  cn(
    "flex w-full rounded-md border bg-transparent px-3 py-1 text-sm transition-colors",
    "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    "disabled:cursor-not-allowed disabled:opacity-50",
  ),
  {
    variants: {
      variant: {
        default: "border-input shadow-sm",
        /** Sits inside other chrome: same padding, no box until hover/focus. */
        ghost:
          "border-transparent shadow-none hover:border-border focus-visible:border-input",
      },
      inputSize: {
        sm: "h-8 text-xs",
        default: "h-9",
        lg: "h-11 text-base",
      },
    },
    defaultVariants: { variant: "default", inputSize: "default" },
  },
);

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size">,
    VariantProps<typeof inputVariants> {}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, variant, inputSize, type, ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(inputVariants({ variant, inputSize }), className)}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { inputVariants };
