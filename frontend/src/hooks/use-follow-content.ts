"use client";

import { useEffect } from "react";

/**
 * Keep a scroller pinned to its bottom while the content inside it grows.
 *
 * An effect on the transcript's data scrolls when a message changes, which
 * stops being enough once the text is revealed over frames after the data has
 * settled: the last lines of an answer grew below the fold, unfollowed. This
 * watches the content's size instead, so any growth - a reveal, an image
 * loading, a step expanding - is followed.
 *
 * `paused` is asked on each resize, not captured: the reader scrolled up to
 * read something and should be left there, or there is nothing to follow yet -
 * an empty conversation's welcome reads from its top.
 */
export function useFollowContent(
  scroller: React.RefObject<HTMLElement | null>,
  content: React.RefObject<HTMLElement | null>,
  paused?: () => boolean,
): void {
  useEffect(() => {
    const scrolling = scroller.current;
    const growing = content.current;
    if (scrolling === null || growing === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (paused?.()) return;
      scrolling.scrollTop = scrolling.scrollHeight;
    });
    observer.observe(growing);
    // And the scroller itself, which shrinks when a phone's keyboard opens: the
    // content did not grow, so without this the last message slid under the
    // keyboard while the reader was following along (#2066).
    observer.observe(scrolling);
    return () => observer.disconnect();
  }, [scroller, content, paused]);
}
