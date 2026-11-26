"use client";

import { useEffect, useState, type RefObject } from "react";

const NO_VISIBLE_BANDS: readonly string[] = [];

/** Fill unused list height one band at a time without persisting automatic choices. */
export function useFillChatBands(
  scroller: RefObject<HTMLElement | null>,
  candidates: readonly string[],
  visible: readonly string[] = NO_VISIBLE_BANDS,
): readonly string[] {
  const [opened, setOpened] = useState<readonly string[]>([]);
  // A short listing can become a long one when the first message is sent or
  // another page arrives. Preserve the bands the reader could already see.
  const additions = visible.filter((key) => !opened.includes(key));
  if (additions.length > 0) setOpened([...opened, ...additions]);
  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const fill = () => {
      if (element.clientHeight === 0 || element.scrollHeight > element.clientHeight) return;
      // scrollHeight is at least clientHeight even when the content is short.
      const contentHeight = Array.from(element.children).reduce(
        (height, child) => height + child.getBoundingClientRect().height,
        0,
      );
      const style = getComputedStyle(element);
      const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
      if (contentHeight + (Number.isFinite(padding) ? padding : 0) >= element.clientHeight) return;
      const next = candidates.find((key) => !opened.includes(key));
      if (next) setOpened((current) => (current.includes(next) ? current : [...current, next]));
    };
    const observer = new ResizeObserver(fill);
    observer.observe(element);
    if (element.firstElementChild) observer.observe(element.firstElementChild);
    fill();
    return () => observer.disconnect();
  }, [scroller, candidates, opened]);
  return opened;
}
