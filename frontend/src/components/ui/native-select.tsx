import * as React from "react";

import { FORM_CONTROL } from "./control-styles";
import { cn } from "@/lib/utils";

/** Native options and keyboard behaviour, with the same surface as SelectTrigger. */
export const NativeSelect = React.forwardRef<HTMLSelectElement, React.ComponentProps<"select">>(
  ({ className, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(FORM_CONTROL, "touch:min-h-11 h-10 px-3 py-1.5 text-sm", className)}
      {...props}
    />
  ),
);
NativeSelect.displayName = "NativeSelect";
