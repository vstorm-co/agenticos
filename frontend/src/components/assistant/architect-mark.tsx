"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const SIZES = {
  sm: "h-6 w-6",
  lg: "h-14 w-14",
} as const;

/** The blueprint's own blue, the one colour the Architect wears in every theme. */
const BLUEPRINT = "#2557d6";

/** How far the eyes travel from centre, in the mark's 24-unit drawing. */
const REACH = { x: 1.6, y: 1.2 } as const;

/** A point on the screen, in CSS pixels. */
interface Point {
  x: number;
  y: number;
}

/**
 * Where the eyes look: towards `target` from the mark's centre, as an offset in
 * the drawing's units - a direction, not a distance, so text typed far below
 * looks down rather than off the face.
 */
export function gazeToward(mark: DOMRect, target: Point): Point {
  const dx = target.x - (mark.left + mark.width / 2);
  const dy = target.y - (mark.top + mark.height / 2);
  const length = Math.hypot(dx, dy);
  if (length < 1) return { x: 0, y: 0 };
  return { x: (dx / length) * REACH.x, y: (dy / length) * REACH.y };
}

/**
 * Where the caret is in a text box, in screen pixels.
 *
 * The width of the caret's line so far, measured in the box's own font, from
 * its left padding; the line is the count of breaks before the caret, at the
 * box's line height. A long line that wraps is placed by where its text would
 * end unwrapped, clamped to the box - near enough for eyes to follow.
 */
export function caretPoint(box: HTMLTextAreaElement): Point {
  const rect = box.getBoundingClientRect();
  const style = getComputedStyle(box);
  const before = box.value.slice(0, box.selectionStart ?? box.value.length);
  const lines = before.split("\n");
  const context = document.createElement("canvas").getContext("2d");
  let width = 0;
  if (context) {
    context.font = style.font;
    width = context.measureText(lines.at(-1) ?? "").width;
  }
  const left = rect.left + (Number.parseFloat(style.paddingLeft) || 0);
  const lineHeight = Number.parseFloat(style.lineHeight) || 20;
  return {
    x: Math.min(left + width, rect.right),
    y: Math.min(
      rect.top + (Number.parseFloat(style.paddingTop) || 0) + (lines.length - 0.5) * lineHeight,
      rect.bottom,
    ),
  };
}

/**
 * The eyes' offset while `watching`: towards the caret of whatever text box has
 * focus, and back to centre when nothing is being typed.
 *
 * Read from the document rather than wired to one composer, so the mark follows
 * the person wherever they type beside it - the welcome screen's composer today.
 */
function useGaze(watching: boolean) {
  const ref = useRef<HTMLSpanElement>(null);
  const [gaze, setGaze] = useState<Point>({ x: 0, y: 0 });
  useEffect(() => {
    if (!watching) return;
    const look = () => {
      const mark = ref.current;
      const box = document.activeElement;
      if (!mark || !(box instanceof HTMLTextAreaElement)) {
        setGaze({ x: 0, y: 0 });
        return;
      }
      setGaze(gazeToward(mark.getBoundingClientRect(), caretPoint(box)));
    };
    document.addEventListener("input", look);
    document.addEventListener("selectionchange", look);
    document.addEventListener("focusin", look);
    document.addEventListener("focusout", look);
    return () => {
      document.removeEventListener("input", look);
      document.removeEventListener("selectionchange", look);
      document.removeEventListener("focusin", look);
      document.removeEventListener("focusout", look);
    };
  }, [watching]);
  return { ref, gaze };
}

/**
 * The Architect's own mark: a blueprint sheet with the agents' two pill eyes.
 *
 * The plan it draws for you, and a member of the same family as every agent's
 * face - the eyes are the ones the avatars wear - in the one colour that says
 * "the platform's own helper" beside agents somebody built. The same mark in
 * light and dark, because a blueprint is blue on either. An organization that
 * gave its Architect a picture sees that picture instead (`AssistantFace`).
 *
 * Alive, a little: it blinks now and then, and `watching` - the large mark over
 * an empty conversation - follows the text being typed with its eyes. Neither
 * moves for a reader who asked for reduced motion.
 */
export function ArchitectMark({
  size,
  watching = false,
  className,
}: {
  /** One of its own sizes; omitted where the caller sizes it through `className`. */
  size?: keyof typeof SIZES;
  /** Follow the caret of the text box being typed in with its eyes. */
  watching?: boolean;
  className?: string;
}) {
  const { ref, gaze } = useGaze(watching);
  return (
    <span
      ref={ref}
      aria-hidden
      className={cn(
        "inline-flex shrink-0 overflow-hidden rounded-full",
        size && SIZES[size],
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="h-full w-full">
        <circle cx="12" cy="12" r="12" fill={BLUEPRINT} />
        {/* The drafting grid, faint, so it reads as paper rather than a pattern. */}
        <g stroke="#fff" strokeOpacity="0.24" strokeWidth="0.45">
          <path d="M0 7.5h24M0 12h24M0 16.5h24M7.5 0v24M12 0v24M16.5 0v24" />
        </g>
        {/* The eyes every agent in the console wears. */}
        <g
          data-testid="architect-eyes"
          className="transition-transform duration-200 ease-out motion-reduce:transition-none"
          style={{ transform: `translate(${gaze.x}px, ${gaze.y}px)` }}
        >
          <g className="origin-center [transform-box:fill-box] motion-safe:animate-[architect-blink_5.5s_ease-in-out_infinite]">
            <rect x="8.4" y="8.9" width="2.3" height="4.9" rx="1.15" fill="#fff" />
            <rect x="13.3" y="8.9" width="2.3" height="4.9" rx="1.15" fill="#fff" />
          </g>
        </g>
      </svg>
    </span>
  );
}
