"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

interface CatalogSectionProps {
  /** The band's label, with its count. */
  title: string;
  defaultOpen: boolean;
  /** Open whatever was chosen before - a link or a search that only it answers. */
  forceOpen?: boolean;
  /** Where this browser remembers the band folded or unfolded; absent remembers nothing. */
  storageKey?: string;
  /** The onboarding anchor on the band's toggle. */
  tour?: string;
  children: ReactNode;
}

function remembered(key: string): boolean | null {
  try {
    const value = window.localStorage.getItem(key);
    return value === null ? null : value === "open";
  } catch {
    return null;
  }
}

function remember(key: string, open: boolean) {
  try {
    window.localStorage.setItem(key, open ? "open" : "closed");
  } catch {
    // A browser refusing storage forgets the choice, which is all it costs.
  }
}

function subscribe(changed: () => void) {
  window.addEventListener("storage", changed);
  return () => window.removeEventListener("storage", changed);
}

/** One band of the agents catalog, folded and unfolded the way a dashboard section is. */
export function CatalogSection({
  title,
  defaultOpen,
  forceOpen = false,
  storageKey,
  tour,
  children,
}: CatalogSectionProps) {
  // The server has no storage, so it renders the default, and the stored choice
  // takes over once the browser can read it.
  const stored = useSyncExternalStore(
    subscribe,
    () => (storageKey === undefined ? null : remembered(storageKey)),
    () => null,
  );
  const [chosen, setChosen] = useState<boolean | null>(null);
  const shown = (chosen ?? stored ?? defaultOpen) || forceOpen;

  return (
    <section className="space-y-3">
      <h2>
        <button
          type="button"
          aria-expanded={shown}
          data-tour={tour}
          onClick={() => {
            setChosen(!shown);
            if (storageKey !== undefined) remember(storageKey, !shown);
          }}
          className="text-muted-foreground hover:text-foreground -ml-1 flex items-center gap-2 font-mono text-xs font-medium tracking-[0.1em] uppercase"
        >
          {shown ? (
            <ChevronDown className="size-4" aria-hidden />
          ) : (
            <ChevronRight className="size-4" aria-hidden />
          )}
          {title}
        </button>
      </h2>
      {shown && children}
    </section>
  );
}
