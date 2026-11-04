"use client";

import { useRef, useState, type PointerEvent, type ReactNode } from "react";
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
  className,
  children,
}: {
  onApprove: () => void;
  onReject: () => void;
  approveLabel: string;
  rejectLabel: string;
  disabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  // Following the finger, which no transition may lag behind.
  const [dragging, setDragging] = useState(false);
  const drag = useRef<Drag | null>(null);
  const past = useRef(false);

  const reset = () => {
    drag.current = null;
    past.current = false;
    setDragging(false);
    setOffset(0);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.pointerType !== "touch") return;
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
        drag.current = null;
        return;
      }
      current.axis = "x";
      setDragging(true);
      event.currentTarget.setPointerCapture?.(event.pointerId);
    }
    setOffset(dx);
    const beyond = Math.abs(dx) >= SWIPE_THRESHOLD;
    if (beyond !== past.current) {
      past.current = beyond;
      if (beyond) haptic("threshold");
    }
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const decided = current.axis === "x" && past.current;
    const approve = offset > 0;
    reset();
    if (!decided) return;
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
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={reset}
        style={{ transform: offset === 0 ? undefined : `translateX(${offset}px)` }}
        className={cn(
          "bg-card relative touch-pan-y",
          !dragging && "transition-transform duration-200",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}
