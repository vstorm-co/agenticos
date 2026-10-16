"use client";

import { useEffect, useRef, useState } from "react";

import {
  ARTIFACT_SANDBOX,
  LinkRequestDialog,
  useLinkRequests,
} from "@/components/artifacts/artifact-frame";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { clampHeight, visualFrameUrl, type VisualKind } from "@/lib/visuals";
import { getResolvedTheme, useThemeStore } from "@/stores/theme-store";

/** How long a finished drawing may go without a heartbeat before it is taken down. */
const STALL_MS = 8000;

/** How many times a finished drawing may grow the frame on its own. */
const MAX_GROWTHS = 4;

/**
 * How tall a drawing may stand under the message.
 *
 * The whole drawing is always shown - a frame that scrolls inside a scrolling
 * conversation hides half a poster behind a scrollbar nobody sees - so one taller
 * than this is shrunk to it rather than cut. An SVG is fitted by its `viewBox`
 * and redraws itself crisply at that size; a page is laid out at the panel's
 * width, measured, and scaled. Full screen shows either at its own size, and
 * interaction still works through the scale.
 */
const PREVIEW_MAX_HEIGHT = 560;

/** A ceiling on a page's measured height, past which it is not worth laying out. */
const MAX_NATURAL = 6000;

export interface VisualFrameProps {
  kind: VisualKind;
  title: string;
  content: string;
  /** Complete: the whole document is written and its scripts run. */
  done: boolean;
  /** The height the call asked to start at. */
  height: number;
  /** Height over width, when the drawing declares it (an SVG's `viewBox`). */
  aspect?: number | null;
  /** Fill the parent rather than fit the drawing - full screen. */
  fill?: boolean;
  onError?: (message: string) => void;
  /** The finished drawing has loaded and run its scripts for a moment. */
  onRendered?: () => void;
  onStall?: () => void;
}

/**
 * One visual in the renderer page, on the content origin, under the app sandbox.
 *
 * The page holds no drawing: this posts it in. While it streams it is posted as
 * it grows, and the frame shows it inert; once it is done it is posted once more
 * as `final`, and the frame writes it as a whole document so its scripts run.
 * Posting to `*` is deliberate - the frame's origin is opaque and cannot be
 * named - and gives away nothing: what is posted is the drawing it is there to
 * show.
 */
export function VisualFrame({
  kind,
  title,
  content,
  done,
  height,
  aspect = null,
  fill = false,
  onError,
  onRendered,
  onStall,
}: VisualFrameProps) {
  const { artifactUrl } = usePublicConfig();
  const theme = getResolvedTheme(useThemeStore((state) => state.theme));
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [reported, setReported] = useState<number | null>(null);
  const finalSent = useRef(false);
  const growths = useRef(0);
  const alive = useRef(0);
  const [pending, setPending] = useLinkRequests(frame);
  const box = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState(0);
  const handlers = useRef({ onError, onRendered, onStall });
  useEffect(() => {
    handlers.current = { onError, onRendered, onStall };
  });

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      if (frame.current === null || event.source !== frame.current.contentWindow) return;
      const data: unknown = event.data;
      if (typeof data !== "object" || data === null) return;
      const message = data as { type?: unknown; height?: unknown; message?: unknown };
      if (message.type === "agenticos:visual-ready") setReady(true);
      else if (message.type === "agenticos:visual-rendered") handlers.current.onRendered?.();
      else if (message.type === "agenticos:visual-alive") alive.current = Date.now();
      else if (message.type === "agenticos:visual-size" && typeof message.height === "number") {
        const next = message.height;
        setReported((current) => {
          // A page sized to its own viewport (`100vh` plus a margin) grows the
          // frame, which grows the page; a few growths and it is held.
          if (current !== null && next > current) {
            growths.current += 1;
            if (growths.current > MAX_GROWTHS) return current;
          }
          return next;
        });
      } else if (message.type === "agenticos:visual-error" && typeof message.message === "string") {
        handlers.current.onError?.(message.message);
      }
    };
    window.addEventListener("message", listen);
    return () => window.removeEventListener("message", listen);
  }, []);

  useEffect(() => {
    const target = frame.current?.contentWindow;
    if (!ready || !target || finalSent.current) return;
    if (done) {
      finalSent.current = true;
      alive.current = Date.now();
      target.postMessage({ type: "agenticos:visual", phase: "final", kind, title, content }, "*");
    } else if (content !== "") {
      target.postMessage(
        { type: "agenticos:visual", phase: "stream", kind, title, content, theme },
        "*",
      );
    }
  }, [ready, done, kind, title, content, theme]);

  useEffect(() => {
    const element = box.current;
    if (fill || element === null) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry !== undefined) setBoxWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [fill]);

  // A drawing that locks up its frame stops beating; it is taken down rather
  // than left to hold the tab. Only while the tab is visible - a hidden one has
  // its timers throttled, and that is not a stall.
  useEffect(() => {
    if (!done) return;
    alive.current = Date.now();
    const check = setInterval(() => {
      if (document.visibilityState !== "visible") {
        alive.current = Date.now();
        return;
      }
      if (Date.now() - alive.current > STALL_MS) {
        clearInterval(check);
        handlers.current.onStall?.();
      }
    }, 2000);
    return () => clearInterval(check);
  }, [done]);

  const measured = boxWidth > 0;
  let preview: React.CSSProperties;
  let boxHeight: number;
  if (aspect !== null) {
    const width = Math.min(boxWidth, PREVIEW_MAX_HEIGHT / aspect);
    boxHeight = measured ? width * aspect : clampHeight(height);
    preview = { width, height: boxHeight, marginLeft: (boxWidth - width) / 2 };
  } else {
    const natural = Math.min(MAX_NATURAL, Math.max(1, reported ?? clampHeight(height)));
    const scale = Math.min(1, PREVIEW_MAX_HEIGHT / natural);
    boxHeight = natural * scale;
    preview = {
      width: boxWidth,
      height: natural,
      transform: `scale(${scale})`,
      transformOrigin: "top left",
      marginLeft: (boxWidth * (1 - scale)) / 2,
    };
  }
  const iframe = (
    <iframe
      ref={frame}
      src={visualFrameUrl(artifactUrl)}
      title={title}
      sandbox={ARTIFACT_SANDBOX}
      referrerPolicy="no-referrer"
      scrolling={fill ? undefined : "no"}
      // The drawing reads `prefers-color-scheme`, which inside a frame follows
      // the colour scheme of the element framing it.
      style={
        fill
          ? { colorScheme: theme }
          : { ...preview, colorScheme: theme, visibility: measured ? "visible" : "hidden" }
      }
      className={fill ? "h-full w-full border-0" : "block border-0"}
    />
  );
  return (
    <>
      {fill ? (
        iframe
      ) : (
        <div ref={box} className="w-full overflow-hidden" style={{ height: Math.round(boxHeight) }}>
          {iframe}
        </div>
      )}
      <LinkRequestDialog pending={pending} onDone={() => setPending(null)} />
    </>
  );
}
