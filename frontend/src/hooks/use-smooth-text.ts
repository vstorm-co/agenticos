"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

/** How long a frame waits before painting more text: ~30 fps, enough to read as flow. */
const FRAME_MS = 32;
/**
 * The share of the backlog revealed per frame. A constant rate would fall behind a
 * fast model and crawl on a slow one; a share of what is waiting keeps the reveal a
 * fraction of a second behind the stream whatever its speed, and eases into the end.
 */
const CATCH_UP = 0.1;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * How much text a bubble may open on and still flow in from nothing. A fast model
 * delivers its first sentence in a single chunk, and showing that at once is the
 * hard edge this hook exists to remove; past this, the bubble is a conversation
 * reopened mid-turn, and replaying what somebody already read would be noise.
 */
const REPLAY_LIMIT = 280;

/**
 * The longest run without whitespace still treated as one word. Past it the text is
 * a URL, a hash, or a script written without spaces, and waiting for the end of the
 * "word" would stall the reveal - Chinese would arrive a line at a time.
 */
const LONGEST_WORD = 16;

const SPACE = /\s/;

/**
 * Move a cut to a word boundary, so a word surfaces whole rather than a letter
 * at a time behind its own fade.
 *
 * Forward to the end of the word the cut lands in; and while the text is still
 * arriving, back to the start of its last word, which may be only half here - a
 * word shown as `lang` that becomes `language` would finish without a fade.
 */
export function wordCut(text: string, cut: number, live: boolean): number {
  let end = cut;
  while (end < text.length && end - cut < LONGEST_WORD && !SPACE.test(text.charAt(end))) end += 1;
  if (live && end === text.length) {
    let start = end;
    while (start > 0 && end - start < LONGEST_WORD && !SPACE.test(text.charAt(start - 1)))
      start -= 1;
    if (end - start < LONGEST_WORD) return start;
  }
  return end;
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
 * toward the latest text a little each frame, a whole word at a time. A short
 * opening flows in from nothing; a long one is a conversation reopened mid-turn and
 * is shown at once, and a turn that ends with text still waiting finishes its
 * reveal rather than jumping. Anyone who asked the system for less motion gets the text
 * as it arrives.
 */
export function useSmoothText(text: string, streaming: boolean): string {
  const [shown, setShown] = useState(() =>
    streaming && text.length <= REPLAY_LIMIT ? 0 : text.length,
  );
  // The frame loop reads the newest text without restarting on every token.
  const target = useRef(text);
  const live = useRef(streaming);
  useLayoutEffect(() => {
    target.current = text;
    live.current = streaming;
  }, [text, streaming]);

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
          const cut = wordCut(target.current, Math.min(goal, next), live.current);
          // Held back on a half-arrived word: stay put until the rest of it lands.
          return Math.max(current, safeCut(target.current, cut));
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

/**
 * `active`, held true for `ms` after it turns false.
 *
 * For an effect that has to outlive its cause: a streamed word keeps its fade-in
 * span until the fade has finished, rather than losing it - and popping to full
 * strength - the moment the turn ends.
 */
export function useLinger(active: boolean, ms: number): boolean {
  const [previous, setPrevious] = useState(active);
  const [tail, setTail] = useState(false);
  if (previous !== active) {
    setPrevious(active);
    setTail(!active);
  }

  useEffect(() => {
    if (!tail) return;
    const timer = setTimeout(() => setTail(false), ms);
    return () => clearTimeout(timer);
  }, [tail, ms]);

  return active || tail;
}
