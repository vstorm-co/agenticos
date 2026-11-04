"use client";

import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Empty states share the console's quiet surfaces. Reserve semantic colours
 * for outcomes that need attention rather than colouring an absence of data.
 */
export function SectionGlyph({ icon: Icon, className }: { icon: LucideIcon; className?: string }) {
  return (
    <div
      aria-hidden
      className={cn(
        "bg-muted/70 text-muted-foreground flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl",
        className,
      )}
    >
      <Icon className="h-6 w-6" strokeWidth={1.6} />
    </div>
  );
}
