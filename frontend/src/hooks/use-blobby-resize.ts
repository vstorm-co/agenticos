"use client";

import { useEffect, useRef, useState } from "react";

import { BLOBBY_SIZE, resizeBlobby } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";

/** How often a resize in progress is sent to the shell, which resizes the window and saves it. */
const SEND_EVERY_MS = 80;
/** How far one notch of the wheel - or one step of a pinch reported as one - scales it. */
const WHEEL_SENSITIVITY = 0.01;

export function clampSize(size: number): number {
  return Math.min(BLOBBY_SIZE.max, Math.max(BLOBBY_SIZE.min, size));
}

/** WebKit's pinch: a `gesturechange` carrying the scale since the pinch began. */
interface GestureEvent extends UIEvent {
  scale: number;
}

function isGesture(event: Event): event is GestureEvent {
  return "scale" in event && typeof event.scale === "number";
}

/**
 * Blobby made bigger or smaller where it stands: a pinch on the trackpad, or
 * the scroll wheel with ⌘ or Ctrl held.
 *
 * The face follows the hand at once, from local state; the shell is told at
 * most every `SEND_EVERY_MS`, and it resizes the window around the feet and
 * keeps the size. Its answer arrives as `size` and wins once the hand stops.
 *
 * WebKit reports a pinch as `gesture*` events and Chromium as a wheel with
 * `ctrlKey`, so both are read. The listeners are not passive - the page must
 * not zoom - which is why they are attached here rather than through React,
 * whose wheel listener is passive.
 */
export function useBlobbyResize(size: number) {
  const target = useRef<HTMLDivElement>(null);
  const [live, setLive] = useState<number | null>(null);
  const current = useRef(size);
  const pinchFrom = useRef(size);
  /** Counts moves, so an answer to an earlier one does not end a pinch still going on. */
  const moves = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    current.current = size;
  }, [size]);

  useEffect(() => {
    const node = target.current;
    /* v8 ignore next -- blobby renders the element unconditionally, so it is mounted by now */
    if (!node) return;
    const send = () => {
      timer.current = undefined;
      const sent = moves.current;
      resizeBlobby(current.current)
        // The shell emits the new settings before it answers, so by now `size`
        // is the new one; the hand's own copy is needed only while it moves.
        .then(() => {
          if (moves.current === sent) setLive(null);
        })
        .catch((error: unknown) => reportShellFailure("could not resize blobby", error));
    };
    const resize = (next: number) => {
      const clamped = clampSize(next);
      current.current = clamped;
      moves.current += 1;
      setLive(clamped);
      timer.current ??= setTimeout(send, SEND_EVERY_MS);
    };
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      resize(current.current * Math.exp(-event.deltaY * WHEEL_SENSITIVITY));
    };
    const onGestureStart = (event: Event) => {
      event.preventDefault();
      pinchFrom.current = current.current;
    };
    const onGestureChange = (event: Event) => {
      event.preventDefault();
      if (isGesture(event)) resize(pinchFrom.current * event.scale);
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    node.addEventListener("gesturestart", onGestureStart);
    node.addEventListener("gesturechange", onGestureChange);
    return () => {
      node.removeEventListener("wheel", onWheel);
      node.removeEventListener("gesturestart", onGestureStart);
      node.removeEventListener("gesturechange", onGestureChange);
      clearTimeout(timer.current);
    };
  }, []);

  return { ref: target, size: live ?? size };
}
