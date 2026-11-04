import * as React from "react";
import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => {
  return (
    <textarea
      className={cn(
        // Matches `Input`: `FormField` marks a refused value with
        // `aria-invalid`, and that has to be visible on the control itself.
        "border-input text-foreground placeholder:text-muted-foreground focus-visible:ring-ring aria-invalid:border-destructive aria-invalid:focus-visible:ring-destructive bg-card flex min-h-24 w-full min-w-0 scroll-m-4 rounded-lg border px-3 py-2 text-base leading-relaxed transition-colors duration-[var(--duration-fast)] focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";

export { Textarea };
