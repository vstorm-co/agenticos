"use client";

import { useState } from "react";

/** The content enters from the side toward which the reader is navigating. */
export function useStepDirection(index: number): "forward" | "backward" {
  const [previous, setPrevious] = useState<{ index: number; direction: "forward" | "backward" }>({
    index,
    direction: "forward",
  });
  if (index !== previous.index) {
    setPrevious({ index, direction: index < previous.index ? "backward" : "forward" });
  }
  return previous.direction;
}
