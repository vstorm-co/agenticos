"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

interface CatalogSectionProps {
  /** The band's label, with its count. */
  title: string;
  defaultOpen: boolean;
  /** The onboarding anchor on the band's toggle. */
  tour?: string;
  children: ReactNode;
}

/** One band of the agents catalog, folded and unfolded the way a dashboard section is. */
export function CatalogSection({ title, defaultOpen, tour, children }: CatalogSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="space-y-3">
      <h2>
        <button
          type="button"
          aria-expanded={open}
          data-tour={tour}
          onClick={() => setOpen((current) => !current)}
          className="text-muted-foreground hover:text-foreground -ml-1 flex items-center gap-2 font-mono text-xs font-medium tracking-[0.1em] uppercase"
        >
          {open ? (
            <ChevronDown className="size-4" aria-hidden />
          ) : (
            <ChevronRight className="size-4" aria-hidden />
          )}
          {title}
        </button>
      </h2>
      {open && children}
    </section>
  );
}
