"use client";

import { useEffect, useRef, useState } from "react";

import { ARTIFACT_SANDBOX } from "@/components/artifacts/artifact-frame";
import { useArtifactView } from "@/hooks/use-artifacts";

/** The width the page is laid out at before it is scaled into the card. */
const VIEWPORT_WIDTH = 1280;
const VIEWPORT_HEIGHT = 960;

/**
 * Whether the element has come within a screen of the viewport - once true, it
 * stays true, so scrolling back does not unload a frame that already painted.
 * False where the browser has no observer (a test environment): nothing loads.
 */
function useNearViewport(ref: React.RefObject<HTMLElement | null>): boolean {
  const [near, setNear] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (element === null || near || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true);
      },
      { rootMargin: "240px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, near]);
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
 * show what a report looks like before it is opened. It is loaded only once the
 * card nears the viewport - the signed address is a request per card and the
 * frame runs the page's script - and it runs in the same sandbox the detail
 * page uses, never with `allow-same-origin`.
 *
 * Inert: no pointer events, out of the tab order and hidden from assistive
 * technology, because the card around it is the link and carries the title.
 * Until it paints, the paper shows placeholder lines; then the page fades in.
 */
export function ArtifactThumbnail({ artifactId, title }: { artifactId: string; title: string }) {
  const box = useRef<HTMLDivElement>(null);
  const near = useNearViewport(box);
  const scale = useFitScale(box);
  const view = useArtifactView(artifactId, null, near);
  const [loaded, setLoaded] = useState(false);

  return (
    <div ref={box} className="relative h-full w-full overflow-hidden">
      {!loaded && (
        <div aria-hidden className="space-y-2 p-3.5">
          <div className="bg-muted h-2.5 w-2/5 animate-pulse rounded" />
          <div className="bg-muted h-2 w-4/5 animate-pulse rounded" />
          <div className="bg-muted h-2 w-3/5 animate-pulse rounded" />
          <div className="grid grid-cols-3 gap-2 pt-1">
            <div className="bg-muted h-8 animate-pulse rounded" />
            <div className="bg-muted h-8 animate-pulse rounded" />
            <div className="bg-muted h-8 animate-pulse rounded" />
          </div>
        </div>
      )}
      {view.data !== undefined && (
        <iframe
          src={view.data.url}
          title={title}
          sandbox={ARTIFACT_SANDBOX}
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
