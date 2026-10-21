"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/** A navigation faster than this shows nothing: a bar that blinks reads as a glitch. */
export const SHOW_AFTER_MS = 120;
/** How long the finished bar takes to fill and fade. */
export const FINISH_MS = 260;
/** A click whose navigation never arrives - cancelled, or refused - lets the bar go. */
export const GIVE_UP_MS = 15_000;

/**
 * The link a click is about to follow inside the console, or `null` for one the
 * browser handles itself: a new tab, a download, another site, or the page
 * already open.
 */
export function navigationTarget(event: MouseEvent): URL | null {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
    return null;
  }
  const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if ((anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) return null;
  const url = new URL(anchor.href);
  const here = window.location;
  if (url.origin !== here.origin) return null;
  if (url.pathname === here.pathname && url.search === here.search) return null;
  return url;
}

type Phase = "idle" | "pending" | "done";

function clearAll(timers: { current: number[] }): void {
  for (const id of timers.current) window.clearTimeout(id);
  timers.current = [];
}

/**
 * A thin bar along the top edge while a click on a link is on its way to the
 * next page. The App Router keeps the old page on screen until the new one is
 * ready, so without it a slow navigation - a route compiled on first visit in
 * development, a large page's code on a slow connection - looked like a click
 * that did nothing.
 *
 * Started by the click itself, in the capture phase, before `next/link` takes
 * it over; finished when the address changes. Neutral ink, as every signal in
 * the console is, and still under reduced motion.
 */
export function NavigationProgress() {
  const t = useTranslations("nav");
  const location = `${usePathname()}?${useSearchParams().toString()}`;
  const [phase, setPhase] = useState<Phase>("idle");
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (navigationTarget(event) === null) return;
      clearAll(timers);
      timers.current = [
        window.setTimeout(() => setPhase("pending"), SHOW_AFTER_MS),
        window.setTimeout(() => setPhase("idle"), GIVE_UP_MS),
      ];
    };
    document.addEventListener("click", onClick, { capture: true });
    return () => {
      document.removeEventListener("click", onClick, { capture: true });
      clearAll(timers);
    };
  }, []);

  // Arrived: whatever was waiting to show no longer will, and a shown bar finishes.
  const [arrivedAt, setArrivedAt] = useState(location);
  if (arrivedAt !== location) {
    setArrivedAt(location);
    setPhase((was) => (was === "pending" ? "done" : "idle"));
  }
  useEffect(() => clearAll(timers), [location]);

  useEffect(() => {
    if (phase !== "done") return;
    const id = window.setTimeout(() => setPhase("idle"), FINISH_MS);
    return () => window.clearTimeout(id);
  }, [phase]);

  if (phase === "idle") return null;
  return (
    <div
      role="progressbar"
      aria-label={t("loadingPage")}
      data-phase={phase}
      className="pointer-events-none fixed inset-x-0 top-0 z-[200] h-0.5"
    >
      <div
        className={cn(
          "bg-foreground/70 h-full origin-left",
          phase === "pending"
            ? "animate-[nav-progress_8s_cubic-bezier(0.08,0.7,0.2,1)_forwards] motion-reduce:scale-x-90 motion-reduce:animate-none"
            : "scale-x-100 opacity-0 transition-[transform,opacity] duration-[260ms] ease-out",
        )}
      />
    </div>
  );
}
