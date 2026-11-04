"use client";

import * as React from "react";
import * as ProgressPrimitive from "@radix-ui/react-progress";
import { cn } from "@/lib/utils";

const Progress = React.forwardRef<
  React.ComponentRef<typeof ProgressPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root>
>(({ className, value, max = 100, ...props }, ref) => {
  const limit = Number.isFinite(max) && max > 0 ? max : 100;
  const measured =
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(limit, Math.max(0, value))
      : null;
  return (
    <ProgressPrimitive.Root
      ref={ref}
      value={measured}
      max={limit}
      className={cn("bg-brand-subtle relative h-2 w-full overflow-hidden rounded-full", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className="bg-brand h-full w-full flex-1 transition-transform duration-[var(--duration-base)] ease-out data-[state=indeterminate]:animate-pulse data-[state=indeterminate]:opacity-40"
        style={
          measured === null
            ? undefined
            : { transform: `translateX(-${100 - (measured / limit) * 100}%)` }
        }
      />
    </ProgressPrimitive.Root>
  );
});
Progress.displayName = ProgressPrimitive.Root.displayName;

export { Progress };
