"use client";

import { useEffect, useRef, useState } from "react";

import { useArtifactView } from "@/hooks/use-artifacts";
import { cn } from "@/lib/utils";

/**
 * Script, and nothing else: no dialogs, no forms, no popups, no same origin.
 *
 * Script because the pages that most need a preview are dashboards whose charts
 * a library draws, and with none they were an empty canvas on their card (#1968).
 * No `allow-modals`, so an `alert()` on load is a no-op rather than a dialog over
 * the listing. What script still costs - a page that loops or spawns workers - is
 * bounded by where it runs: a thumbnail is mounted only while its card is near
 * the viewport and unmounted when it leaves (`useNearViewport`), so a listing of
 * fifty runs the few a reader can see.
 */
const THUMBNAIL_SANDBOX = "allow-scripts";

/** The width the page is laid out at before it is scaled into the card. */
const VIEWPORT_WIDTH = 1280;
const VIEWPORT_HEIGHT = 960;

/**
 * Whether the element is within a screen of the viewport, now - not once.
 * Scrolling away unmounts the frame, which is what stops a scripted page in a
 * card nobody is looking at. False where the browser has no observer (a test
 * environment): nothing loads.
 */
function useNearViewport(ref: React.RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (element === null || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[entries.length - 1];
        if (entry) setNear(entry.isIntersecting);
      },
      { rootMargin: "240px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return near;
}

/** How far a `VIEWPORT_WIDTH` page must shrink to fit the element's width. */
function useFitScale(ref: React.RefObject<HTMLElement | null>): number {
  const [scale, setScale] = useState(0.25);
  useEffect(() => {
    const element = ref.current;
    if (element === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setScale(entry.contentRect.width / VIEWPORT_WIDTH);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return scale;
}

/**
 * The artifact's current page, live and shrunk to a thumbnail.
 *
 * The real page rather than a screenshot, because none is kept: an artifact is
 * the HTML an agent published, and this is the one place in a listing that can
 * show what a report looks like before it is opened. It is loaded only while the
 * card is near the viewport - the signed address is a request per card - and in
 * a sandbox that allows script and nothing more, see `THUMBNAIL_SANDBOX`.
 *
 * Inert: no pointer events, out of the tab order and hidden from assistive
 * technology, because the card around it is the link and carries the title.
 * Until it paints, the paper shows pulsing placeholder lines; then the page
 * fades in. If the address cannot be had, the lines stay and stop pulsing - a
 * card that pulses forever says "loading" about something that never will.
 */
export function ArtifactThumbnail({ artifactId, title }: { artifactId: string; title: string }) {
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const scale = useFitScale(box);
  const view = useArtifactView(artifactId, null, near);
  const [loaded, setLoaded] = useState(false);
  // A frame unmounted off screen paints again when it comes back, so the lines
  // return with it rather than a blank card waiting for the load.
  const [wasNear, setWasNear] = useState(near);
  if (wasNear !== near) {
    setWasNear(near);
    if (!near) setLoaded(false);
  }
  const line = cn("bg-muted rounded", !view.isError && "animate-pulse");

  return (
    <div ref={box} className="relative h-full w-full overflow-hidden">
      {!loaded && (
        <div aria-hidden data-unavailable={view.isError} className="space-y-2 p-3.5">
          <div className={cn(line, "h-2.5 w-2/5")} />
          <div className={cn(line, "h-2 w-4/5")} />
          <div className={cn(line, "h-2 w-3/5")} />
          <div className="grid grid-cols-3 gap-2 pt-1">
            <div className={cn(line, "h-8")} />
            <div className={cn(line, "h-8")} />
            <div className={cn(line, "h-8")} />
          </div>
        </div>
      )}
      {near && view.data !== undefined && (
        <iframe
          src={view.data.url}
          title={title}
          sandbox={THUMBNAIL_SANDBOX}
          referrerPolicy="no-referrer"
          loading="lazy"
          tabIndex={-1}
          aria-hidden
          onLoad={() => setLoaded(true)}
          data-loaded={loaded}
          className="peek-frame pointer-events-none absolute top-0 left-0 origin-top-left border-0 bg-white"
          style={{
            width: VIEWPORT_WIDTH,
            height: VIEWPORT_HEIGHT,
            transform: `scale(${scale})`,
          }}
        />
      )}
    </div>
  );
}
