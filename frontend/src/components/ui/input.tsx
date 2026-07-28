import * as React from "react";
import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          // `aria-invalid` is what `FormField` sets when the server refuses a
          // value. Without a border to match, the message below the field is
          // the only sign, and on a form with several inputs it does not say
          // which one it is about.
          "border-input file:text-foreground placeholder:text-muted-foreground focus-visible:ring-ring aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive flex h-9 w-full rounded-md border bg-transparent px-3 py-1 text-base shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium focus-visible:ring-1 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
