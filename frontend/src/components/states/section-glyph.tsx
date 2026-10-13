"use client";

import type { LucideIcon } from "lucide-react";

import { useDomainClass } from "@/components/dashboard/page-icon";
import { cn } from "@/lib/utils";

/**
 * An empty state's glyph, in the hue of the section it sits in - the same tile
 * the section page's title carries, so "nothing here yet" still says where
 * "here" is. A client leaf, so the empty states around it can stay server-safe.
 */
export function SectionGlyph({ icon: Icon, className }: { icon: LucideIcon; className?: string }) {
  const domain = useDomainClass();
  return (
    <div
      aria-hidden
      className={cn(
        domain,
        "flex h-11 w-11 items-center justify-center rounded-xl border border-[var(--domain-line)] bg-[var(--domain-subtle)] text-[var(--domain)]",
        className,
      )}
    >
      <Icon className="h-5 w-5" />
    </div>
  );
}
