"use client";

import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { animate, motion, useMotionValue, useTransform } from "motion/react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
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
/** How far a finger moves before it counts as a pull: less is a tap, sideways is a swipe. */
const SLOP = 8;

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
  const [visible, setVisible] = useState(false);
  const distance = useMotionValue(0);
  const y = useTransform(distance, (value) => value - PULL_THRESHOLD / 2);
  const opacity = useTransform(distance, (value) => Math.min(1, value / PULL_THRESHOLD));
  const rotate = useTransform(distance, (value) => value * 4);
  const reduced = useReducedMotion();
  const reducedRef = useRef(reduced);
  useEffect(() => {
    reducedRef.current = reduced;
    if (reduced) distance.jump(0);
  }, [reduced, distance]);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const scroller = document.getElementById("main");
    if (!enabled || !scroller) return;
    let start: { x: number; y: number } | null = null;
    let pulling = false;
    let past = false;
    let busy = false;
    let active = true;
    const settle = () => {
      distance.stop();
      if (reducedRef.current) {
        distance.jump(0);
        setVisible(false);
      } else {
        animate(distance, 0, {
          type: "spring",
          duration: 0.5,
          bounce: 0,
          velocity: distance.getVelocity(),
          onComplete: () => setVisible(false),
        });
      }
    };

    const onStart = (event: TouchEvent) => {
      if (busy || event.touches.length !== 1 || !atTop(event.target, scroller)) return;
      distance.stop();
      start = { x: event.touches[0]!.clientX, y: event.touches[0]!.clientY };
      pulling = false;
      past = false;
    };
    const onMove = (event: TouchEvent) => {
      if (start === null) return;
      if (event.touches.length !== 1) {
        start = null;
        past = false;
        settle();
        return;
      }
      const dx = event.touches[0]!.clientX - start.x;
      const dy = event.touches[0]!.clientY - start.y;
      if (!pulling) {
        if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
        // A swipe sideways - deciding an approval - or up is not a pull.
        if (dy <= Math.abs(dx)) {
          start = null;
          return;
        }
        pulling = true;
      }
      const damped = Math.max(0, dy * DAMPING);
      const over = Math.max(0, damped - PULL_THRESHOLD);
      const remaining = PULL_MAX - PULL_THRESHOLD;
      const pulled = Math.min(damped, PULL_THRESHOLD) + (remaining * over) / (remaining + over);
      setVisible(pulled > 0);
      distance.set(pulled);
      const beyond = pulled >= PULL_THRESHOLD;
      if (beyond !== past) {
        past = beyond;
        if (beyond) haptic("threshold");
      }
    };
    const onEnd = () => {
      if (start === null) return;
      start = null;
      if (!past) {
        settle();
        return;
      }
      past = false;
      busy = true;
      setRefreshing(true);
      distance.jump(PULL_THRESHOLD);
      void queryClient.refetchQueries({ type: "active" }).finally(() => {
        if (!active) return;
        busy = false;
        setRefreshing(false);
        settle();
      });
    };

    const onCancel = () => {
      past = false;
      onEnd();
    };

    scroller.addEventListener("touchstart", onStart, { passive: true });
    scroller.addEventListener("touchmove", onMove, { passive: true });
    scroller.addEventListener("touchend", onEnd);
    scroller.addEventListener("touchcancel", onCancel);
    return () => {
      active = false;
      distance.stop();
      scroller.removeEventListener("touchstart", onStart);
      scroller.removeEventListener("touchmove", onMove);
      scroller.removeEventListener("touchend", onEnd);
      scroller.removeEventListener("touchcancel", onCancel);
    };
  }, [enabled, queryClient, distance]);

  if (!enabled || (!visible && !refreshing)) return null;
  return (
    <div
      aria-hidden
      data-testid="pull-to-refresh"
      className="pointer-events-none fixed inset-x-0 top-[var(--shell-inset-top,0px)] z-50 flex justify-center"
    >
      <motion.span
        className="bg-card text-foreground mt-2 rounded-full border p-2 shadow-sm"
        style={{ y, opacity }}
      >
        <motion.span className="block" style={{ rotate: refreshing ? 0 : rotate }}>
          <RefreshCw className={cn("h-4 w-4", refreshing && "motion-safe:animate-spin")} />
        </motion.span>
      </motion.span>
    </div>
  );
}
