"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { clampHeight } from "@/lib/visuals";
import { VisualFrame, type VisualFrameProps } from "./visual-frame";

function subscribeToCapabilities(): () => void {
  return () => {};
}

/** Release completed offscreen drawings without collapsing their place in history. */
export function ViewportVisualFrame({
  suspended = false,
  ...props
}: VisualFrameProps & { suspended?: boolean }) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [near, setNear] = useState(false);
  const [height, setHeight] = useState(() => clampHeight(props.height));
  const unsupported = useSyncExternalStore(
    subscribeToCapabilities,
    () => typeof IntersectionObserver === "undefined",
    () => false,
  );
  const live = !suspended && (!props.done || near || unsupported);

  useEffect(() => {
    const target = box;
    if (target === null) return;
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.target === target) setNear(entry.isIntersecting);
        }
      },
      { rootMargin: "320px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [box]);

  useEffect(() => {
    const target = box;
    if (!live || target === null) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.target === target && entry.contentRect.height > 0) {
          setHeight(entry.contentRect.height);
        }
      }
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, [box, live]);

  return (
    <div ref={setBox} style={live ? undefined : { height }}>
      {live && <VisualFrame {...props} />}
    </div>
  );
}
