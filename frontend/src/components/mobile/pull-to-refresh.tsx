"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { useMounted } from "@/hooks/use-mounted";
import { isMobileShell, readShellInfo } from "@/lib/desktop/shell";
import { haptic } from "@/lib/mobile/haptics";
import { cn } from "@/lib/utils";

/** How far the page is pulled, after damping, before letting go refreshes it. */
export const PULL_THRESHOLD = 64;
const PULL_MAX = 96;
/** A finger moves twice as far as the page follows it: the pull resists. */
const DAMPING = 0.5;

/** Whether nothing between the touch and the page's scroller is scrolled down. */
function atTop(target: EventTarget | null, scroller: HTMLElement): boolean {
  let node = target instanceof Element ? target : null;
  while (node !== null && node !== scroller) {
    if (node.scrollTop > 0) return false;
    node = node.parentElement;
  }
  return scroller.scrollTop === 0;
}

/** Where a phone pulls to refresh: the phone app, or the console installed to a touch screen. */
function pullable(): boolean {
  return (
    isMobileShell(readShellInfo()) ||
    window.matchMedia?.("(display-mode: standalone) and (pointer: coarse)").matches
  );
}

/**
 * Pull the page down to read it again, as every phone app does (#2097): on
 * the console's scroller (`main`), from the top, with a tap felt when letting
 * go would refresh. What refreshes is every query on screen; a chat's
 * transcript scrolls in its own box, so a pull there begins only when that box
 * is at its top as well.
 */
export function PullToRefresh() {
  const mounted = useMounted();
  const enabled = mounted && pullable();
  const queryClient = useQueryClient();
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const scroller = document.getElementById("main");
    if (!enabled || !scroller) return;
    let startY: number | null = null;
    let past = false;

    const onStart = (event: TouchEvent) => {
      if (event.touches.length !== 1 || !atTop(event.target, scroller)) return;
      startY = event.touches[0]!.clientY;
      past = false;
    };
    const onMove = (event: TouchEvent) => {
      if (startY === null) return;
      const distance = Math.min(
        Math.max(0, (event.touches[0]!.clientY - startY) * DAMPING),
        PULL_MAX,
      );
      setPull(distance);
      const beyond = distance >= PULL_THRESHOLD;
      if (beyond !== past) {
        past = beyond;
        if (beyond) haptic("threshold");
      }
    };
    const onEnd = () => {
      if (startY === null) return;
      startY = null;
      setPull(0);
      if (!past) return;
      past = false;
      setRefreshing(true);
      void queryClient.refetchQueries({ type: "active" }).finally(() => setRefreshing(false));
    };

    scroller.addEventListener("touchstart", onStart, { passive: true });
    scroller.addEventListener("touchmove", onMove, { passive: true });
    scroller.addEventListener("touchend", onEnd);
    scroller.addEventListener("touchcancel", onEnd);
    return () => {
      scroller.removeEventListener("touchstart", onStart);
      scroller.removeEventListener("touchmove", onMove);
      scroller.removeEventListener("touchend", onEnd);
      scroller.removeEventListener("touchcancel", onEnd);
    };
  }, [enabled, queryClient]);

  if (!enabled || (pull === 0 && !refreshing)) return null;
  const shown = refreshing ? PULL_THRESHOLD : pull;
  return (
    <div
      aria-hidden
      data-testid="pull-to-refresh"
      className="pointer-events-none fixed inset-x-0 top-[var(--shell-inset-top,0px)] z-50 flex justify-center"
    >
      <span
        className="bg-card text-foreground mt-2 rounded-full border p-2 shadow-sm"
        style={{
          transform: `translateY(${shown - PULL_THRESHOLD / 2}px)`,
          opacity: shown / PULL_THRESHOLD,
        }}
      >
        <RefreshCw
          className={cn("h-4 w-4", refreshing && "animate-spin")}
          style={refreshing ? undefined : { transform: `rotate(${pull * 4}deg)` }}
        />
      </span>
    </div>
  );
}
