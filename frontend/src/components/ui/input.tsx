import * as React from "react";
import { FORM_CONTROL } from "./control-styles";
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
          FORM_CONTROL,
          "file:text-foreground touch:min-h-11 flex h-10 scroll-m-4 px-3 py-2 text-base file:border-0 file:bg-transparent file:text-sm file:font-medium md:text-sm",
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
