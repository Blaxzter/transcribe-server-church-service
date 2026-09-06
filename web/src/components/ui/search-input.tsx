import * as React from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { de } from "@/i18n/de";
import { Input } from "@/components/ui/input";

export interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "size"> {
  value: string;
  onValueChange: (value: string) => void;
  wrapperClassName?: string;
}

/** Search field with a leading icon and a clear button once it has content. */
export const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  ({ value, onValueChange, className, wrapperClassName, ...props }, ref) => {
    const innerRef = React.useRef<HTMLInputElement>(null);
    React.useImperativeHandle(ref, () => innerRef.current as HTMLInputElement);

    return (
      <div className={cn("relative", wrapperClassName)}>
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={innerRef}
          type="search"
          {...props}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape" && value) {
              event.preventDefault();
              onValueChange("");
            }
            props.onKeyDown?.(event);
          }}
          className={cn("pl-9 pr-9 [&::-webkit-search-cancel-button]:hidden", className)}
        />
        {value && (
          <button
            type="button"
            aria-label={de.common.clear}
            onClick={() => {
              onValueChange("");
              innerRef.current?.focus();
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-sm p-1 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-3.5" />
          </button>
        )}
      </div>
    );
  },
);
SearchInput.displayName = "SearchInput";
