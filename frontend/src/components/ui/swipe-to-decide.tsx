"use client";

import { useEffect, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { animate, motion, useMotionValue, useMotionValueEvent } from "motion/react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { CheckCircle2, XCircle } from "lucide-react";

import { haptic } from "@/lib/mobile/haptics";
import { cn } from "@/lib/utils";

/** How far a row travels before letting go decides it. */
export const SWIPE_THRESHOLD = 96;
/** How far a finger moves before the gesture is read as a swipe or a scroll. */
const SLOP = 8;

interface Drag {
  pointerId: number;
  x: number;
  y: number;
  /** Decided once the finger has moved past `SLOP`: sideways is a swipe. */
  axis: "x" | "y" | null;
}

/**
 * A row a finger swipes to decide (#2097): to the right says yes, to the left
 * says no, as a mail app files a message.
 *
 * Touch only - a mouse drags to select text - and only sideways: a finger
 * moving down the page scrolls it, and the row does not follow. What the row
 * will do shows under it as it moves; a tap is felt when it passes the point
 * where letting go decides, and again when it decides. Short of that point it
 * springs back. The row's own buttons stay, for everybody who does not swipe.
 */
export function SwipeToDecide({
  onApprove,
  onReject,
  approveLabel,
  rejectLabel,
  disabled = false,
  rejectOnly = false,
  className,
  children,
}: {
  onApprove: () => void;
  onReject: () => void;
  approveLabel: string;
  rejectLabel: string;
  disabled?: boolean;
  /** Only the swipe that rejects decides; the row does not follow a finger towards approving. */
  rejectOnly?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const x = useMotionValue(0);
  const reduced = useReducedMotion();
  // Following the finger, which no transition may lag behind.
  const drag = useRef<Drag | null>(null);
  const past = useRef(false);
  useMotionValueEvent(x, "change", (value) => {
    if (value === 0) setOffset(0);
  });
  useEffect(() => () => x.stop(), [x]);
  useEffect(() => {
    if (reduced) {
      drag.current = null;
      past.current = false;
      x.jump(0);
    }
  }, [reduced, x]);

  const reset = () => {
    drag.current = null;
    past.current = false;
    setOffset(0);
    if (reduced) x.jump(0);
    else animate(x, 0, { type: "spring", duration: 0.5, bounce: 0, velocity: x.getVelocity() });
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.pointerType !== "touch" || drag.current) return;
    x.stop();
    drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, axis: null };
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (current.axis === null) {
      if (Math.abs(dx) < SLOP && Math.abs(dy) < SLOP) return;
      if (Math.abs(dy) >= Math.abs(dx)) {
        reset();
        return;
      }
      current.axis = "x";
      event.currentTarget.setPointerCapture?.(event.pointerId);
    }
    const moved = rejectOnly ? Math.min(dx, 0) : dx;
    setOffset(moved);
    x.set(moved);
    const beyond = Math.abs(moved) >= SWIPE_THRESHOLD;
    if (beyond !== past.current) {
      past.current = beyond;
      if (beyond) haptic("threshold");
    }
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const decided = !disabled && current.axis === "x" && past.current;
    const approve = x.get() > 0;
    reset();
    if (!decided || (approve && rejectOnly)) return;
    haptic(approve ? "success" : "warning");
    if (approve) onApprove();
    else onReject();
  };

  return (
    <div className="relative overflow-hidden">
      <div
        aria-hidden
        className={cn(
          "absolute inset-0 flex items-center px-6 text-sm font-medium",
          offset > 0
            ? "bg-success/15 text-success justify-start"
            : "bg-destructive/15 text-destructive justify-end",
          offset === 0 && "invisible",
        )}
      >
        {offset > 0 ? (
          <span className="inline-flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5" />
            {approveLabel}
          </span>
        ) : (
          <span className="inline-flex items-center gap-2">
            {rejectLabel}
            <XCircle className="h-5 w-5" />
          </span>
        )}
      </div>
      <motion.div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={reset}
        style={{ x }}
        className={cn("bg-card relative touch-pan-y", className)}
      >
        {children}
      </motion.div>
    </div>
  );
}
