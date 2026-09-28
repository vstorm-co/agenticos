"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

/** How long a frame waits before painting more text: ~30 fps, enough to read as flow. */
const FRAME_MS = 32;
/**
 * The share of the backlog revealed per frame. A constant rate would fall behind a
 * fast model and crawl on a slow one; a share of what is waiting keeps the reveal a
 * fraction of a second behind the stream whatever its speed, and eases into the end.
 */
const CATCH_UP = 0.18;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

/** Never cut between the two halves of a surrogate pair - an emoji would flash as `�`. */
function safeCut(text: string, length: number): number {
  const code = text.charCodeAt(length - 1);
  return code >= 0xd800 && code <= 0xdbff ? length + 1 : length;
}

/**
 * The streamed text, revealed as a steady flow rather than in the bursts the
 * network delivers it in.
 *
 * Tokens arrive in uneven chunks - a word, then nothing, then half a sentence - and
 * painting each chunk as it lands reads as a stutter. While `streaming`, this paints
 * toward the latest text a little each frame. What had already arrived before the
 * component mounted is shown at once (reopening a conversation mid-turn must not
 * replay it), and a turn that ends with text still waiting finishes its reveal
 * rather than jumping. Anyone who asked the system for less motion gets the text
 * as it arrives.
 */
export function useSmoothText(text: string, streaming: boolean): string {
  const [shown, setShown] = useState(text.length);
  // The frame loop reads the newest text without restarting on every token.
  const target = useRef(text);
  useLayoutEffect(() => {
    target.current = text;
  }, [text]);

  const behind = shown < text.length;
  const animate = (streaming || behind) && !prefersReducedMotion();

  useEffect(() => {
    if (!animate) return;
    let frame = 0;
    let last = 0;
    const step = (now: number) => {
      if (now - last >= FRAME_MS) {
        last = now;
        setShown((current) => {
          const goal = target.current.length;
          if (current >= goal) return goal;
          const next = current + Math.max(1, Math.ceil((goal - current) * CATCH_UP));
          return safeCut(target.current, Math.min(goal, next));
        });
      }
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [animate]);

  // A shorter text than what is shown is a new message in the same slot, or an
  // edit; either way the reveal starts from what is there now.
  if (!animate || shown > text.length) return text;
  return text.slice(0, shown);
}
