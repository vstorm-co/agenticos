"use client";

import { usePathname } from "next/navigation";

import { navSectionFor, type NavDomain } from "@/lib/nav-sections";
import { cn } from "@/lib/utils";

/** The section the current page belongs to - its nav entry and hue - or `null` outside the nav. */
export function useNavSection() {
  return navSectionFor(usePathname());
}

/** The `domain-*` class for the current section, so a component can read `--domain*`. */
export function useDomainClass(fallback: NavDomain = "use"): string {
  return `domain-${useNavSection()?.domain ?? fallback}`;
}

/**
 * The module's own glyph in its section's hue, beside a section page's title.
 *
 * Only on the section's page itself - `/agents`, not `/agents/abc`, where the
 * breadcrumb already says where you are and the title is the thing's own name
 * (often with its own avatar). Outside the nav, nothing: a page with no section
 * has no hue to claim.
 */
export function PageIcon({ className }: { className?: string }) {
  const section = useNavSection();
  if (section === null || !section.isRoot) return null;
  const Icon = section.item.icon;
  return (
    <span
      aria-hidden
      className={cn(
        `domain-${section.domain}`,
        "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[var(--domain-line)] bg-[var(--domain-subtle)] text-[var(--domain)]",
        className,
      )}
    >
      <Icon className="h-5 w-5" />
    </span>
  );
}
