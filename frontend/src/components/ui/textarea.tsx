import * as React from "react";
import { FORM_CONTROL } from "./control-styles";
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
        FORM_CONTROL,
        "flex min-h-24 scroll-m-4 px-3 py-2 text-base leading-relaxed md:text-sm",
        className,
      )}
      ref={ref}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";

export { Textarea };
