"use client";

import { useEffect, useRef, useState } from "react";

import {
  ARTIFACT_SANDBOX,
  LinkRequestDialog,
  useLinkRequests,
} from "@/components/artifacts/artifact-frame";
import { useAskingGate } from "@/hooks/use-artifact-actions";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { clampHeight, visualFrameUrl, type VisualKind } from "@/lib/visuals";
import { cn } from "@/lib/utils";
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
 * interaction still works through the scale. Zoomed in, the drawing is the one
 * thing that scrolls - inside its own box, which a person asked for.
 */
const PREVIEW_MAX_HEIGHT = 560;

/**
 * The same for a page, which is taller: a page is something to use - a map with
 * its stops, a calculator - and shrunk to a poster's height its text and its
 * controls end up too small to read or hit (#2302).
 */
const PAGE_MAX_HEIGHT = 900;

/** A ceiling on a page's measured height, past which it is not worth laying out. */
const MAX_NATURAL = 6000;

/** The longest follow-up a drawing may ask to send - the backend's `FOLLOW_UP_MAX_CHARS`. */
export const FOLLOW_UP_MAX_CHARS = 2000;

/**
 * The text of a follow-up request, or null when the message is not one to show.
 *
 * Refused unless a person has just interacted with the page: a click inside the
 * frame gives this window transient activation too, and a drawing asking on
 * load, on a timer or in a loop has none. That is not what makes it safe - a
 * script can piggyback on any click, a slider drag included - which is why the
 * request is only ever shown, and sent by a click in the console's own DOM.
 * Where the browser cannot say (`userActivation` is missing), the click on Send
 * is the whole guard.
 */
export function followUpText(message: { text?: unknown }): string | null {
  const activation = (navigator as Navigator & { userActivation?: { isActive: boolean } })
    .userActivation;
  if (activation !== undefined && !activation.isActive) return null;
  if (typeof message.text !== "string") return null;
  const text = message.text.trim();
  if (text === "" || text.length > FOLLOW_UP_MAX_CHARS) return null;
  return text;
}

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
  /** How far the person zoomed in, 1 being the drawing fitted to its box. */
  zoom?: number;
  onError?: (message: string) => void;
  /** The finished drawing has loaded and run its scripts for a moment. */
  onRendered?: () => void;
  /** The SVG the drawing ended up as, for a thumbnail - a Mermaid diagram's above all. */
  onSvg?: (markup: string) => void;
  onStall?: () => void;
  /**
   * A control in the finished drawing asked to continue the conversation with
   * this text, after a person clicked it. Present only where the chat can take a
   * follow-up: the drawing is told so, and shows its follow-up buttons.
   */
  onFollowUp?: (text: string) => void;
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
  zoom = 1,
  onError,
  onRendered,
  onSvg,
  onStall,
  onFollowUp,
}: VisualFrameProps) {
  const { artifactUrl } = usePublicConfig();
  const theme = getResolvedTheme(useThemeStore((state) => state.theme));
  const frame = useRef<HTMLIFrameElement>(null);
  const [ready, setReady] = useState(false);
  const [reported, setReported] = useState<number | null>(null);
  const finalSent = useRef(false);
  const growths = useRef(0);
  const alive = useRef(0);
  const asking = useAskingGate();
  const [pending, closeLink] = useLinkRequests(frame, asking);
  const box = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState(0);
  const handlers = useRef({ onError, onRendered, onSvg, onStall, onFollowUp });
  // Read by the message listener, which is set up once.
  const finished = useRef(done);
  useEffect(() => {
    handlers.current = { onError, onRendered, onSvg, onStall, onFollowUp };
    finished.current = done;
  });

  useEffect(() => {
    const listen = (event: MessageEvent) => {
      if (frame.current === null || event.source !== frame.current.contentWindow) return;
      const data: unknown = event.data;
      if (typeof data !== "object" || data === null) return;
      const message = data as {
        type?: unknown;
        height?: unknown;
        message?: unknown;
        markup?: unknown;
        text?: unknown;
      };
      if (message.type === "agenticos:visual-ready") setReady(true);
      else if (message.type === "agenticos:hello") {
        // The finished drawing's platform script, asking what its host offers.
        if (handlers.current.onFollowUp !== undefined) {
          frame.current.contentWindow?.postMessage({ type: "agenticos:host", followUp: true }, "*");
        }
      } else if (message.type === "agenticos:follow-up") {
        const text = followUpText(message);
        if (text !== null) handlers.current.onFollowUp?.(text);
      } else if (message.type === "agenticos:visual-rendered") handlers.current.onRendered?.();
      else if (message.type === "agenticos:visual-svg" && typeof message.markup === "string") {
        handlers.current.onSvg?.(message.markup);
      } else if (message.type === "agenticos:visual-alive") alive.current = Date.now();
      else if (message.type === "agenticos:visual-size" && typeof message.height === "number") {
        // While it streams the drawing keeps the height it declared, so the
        // conversation does not move under the reader as markup arrives; it is
        // fitted to what it measures once it is finished.
        if (!finished.current) return;
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

  // An SVG redraws itself at any size, so it is zoomed by laying it out larger;
  // a page would only reflow wider, so it is laid out once and scaled.
  const measured = boxWidth > 0;
  let laidOut: React.CSSProperties;
  let footprint: { width: number; height: number };
  let boxHeight: number;
  if (aspect !== null) {
    const width = Math.min(boxWidth, PREVIEW_MAX_HEIGHT / aspect);
    boxHeight = measured ? width * aspect : clampHeight(height);
    footprint = { width: width * zoom, height: boxHeight * zoom };
    laidOut = footprint;
  } else {
    const natural = Math.min(MAX_NATURAL, Math.max(1, reported ?? clampHeight(height)));
    const scale = Math.min(1, PAGE_MAX_HEIGHT / natural);
    boxHeight = natural * scale;
    footprint = { width: boxWidth * scale * zoom, height: boxHeight * zoom };
    laidOut = scaled(boxWidth, natural, scale * zoom);
  }
  const fullLaidOut: React.CSSProperties =
    kind === "svg"
      ? { width: "100%", height: "100%" }
      : scaled(`${100 / zoom}%`, `${100 / zoom}%`, zoom);
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
          ? { ...fullLaidOut, colorScheme: theme }
          : { ...laidOut, colorScheme: theme, visibility: measured ? "visible" : "hidden" }
      }
      className="block border-0"
    />
  );
  // The footprint clips the frame to what it shows: a page laid out taller than
  // it is drawn would otherwise give the box empty space to scroll into.
  return (
    <>
      {fill ? (
        <div
          className={cn(
            "h-full w-full",
            zoom > 1 ? "scrollbar-thin overflow-auto" : "overflow-hidden",
          )}
        >
          <div
            className="relative mx-auto overflow-hidden"
            style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%` }}
          >
            {iframe}
          </div>
        </div>
      ) : (
        <div
          ref={box}
          className={cn(
            "w-full transition-[height] duration-200 ease-out motion-reduce:transition-none",
            zoom > 1 ? "scrollbar-thin overflow-auto" : "overflow-hidden",
          )}
          style={{ height: Math.round(boxHeight) }}
        >
          <div
            className="relative overflow-hidden"
            // From the left edge, where the message's text starts: the drawing is
            // part of the answer, not a picture centred in a box of its own.
            style={footprint}
          >
            {iframe}
          </div>
        </div>
      )}
      <LinkRequestDialog pending={pending} onDone={closeLink} />
    </>
  );
}

/** A frame laid out at one size and drawn at another, from its top left corner. */
function scaled(width: number | string, height: number | string, by: number): React.CSSProperties {
  return { width, height, transform: `scale(${by})`, transformOrigin: "top left" };
}
