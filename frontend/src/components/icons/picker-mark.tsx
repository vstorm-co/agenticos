import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A consistent optical box for differently shaped marks in selection fields. */
export function PickerMark({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "bg-background/70 ring-border/60 inline-flex size-6 shrink-0 items-center justify-center rounded-md ring-1 ring-inset [&>span]:size-4 [&>svg]:size-4",
        className,
      )}
    >
      {children}
    </span>
  );
}
