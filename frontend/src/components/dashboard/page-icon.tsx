"use client";

import { usePathname } from "next/navigation";

import { navSectionFor, type NavDomain } from "@/lib/nav-sections";

/** The section the current page belongs to - its nav entry and hue - or `null` outside the nav. */
export function useNavSection() {
  return navSectionFor(usePathname());
}

/** The `domain-*` class for the current section, so a component can read `--domain*`. */
export function useDomainClass(fallback: NavDomain = "use"): string {
  return `domain-${useNavSection()?.domain ?? fallback}`;
}
