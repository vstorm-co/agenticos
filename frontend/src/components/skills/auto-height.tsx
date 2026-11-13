"use client";

import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

/**
 * Its children at their own height, eased to a new one when they change.
 *
 * A dialog centred on the page re-centres on every change of its height, so a note
 * appearing under a choice jumps the whole dialog; easing the height lets it move
 * there instead. Measured rather than `height: auto`, which no transition reaches.
 */
export function AutoHeight({ children }: { children: ReactNode }) {
  const inner = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | null>(null);

  useLayoutEffect(() => {
    const element = inner.current!;
    const measure = () => setHeight(element.offsetHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      className="overflow-hidden transition-[height] duration-200 ease-out motion-reduce:transition-none"
      style={height === null ? undefined : { height }}
    >
      <div ref={inner}>{children}</div>
    </div>
  );
}
