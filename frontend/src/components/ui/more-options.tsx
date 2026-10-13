"use client";

import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The settings a form does not need to be filled in, folded under one line.
 *
 * A create dialog asks for what the thing needs to exist; the rest - a note,
 * a reaction, how answers are drawn - waits here, closed, so the dialog is as
 * short as its required fields. One component, so every dialog folds the same
 * way and says so in the same words.
 */
export function MoreOptions({
  label,
  defaultOpen = false,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-sm font-medium transition-colors"
      >
        <ChevronRight
          className={cn("h-4 w-4 transition-transform", open && "rotate-90")}
          aria-hidden
        />
        {label}
      </button>
      {open && <div className="mt-4 space-y-5">{children}</div>}
    </div>
  );
}
