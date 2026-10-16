"use client";

import { useEffect } from "react";

import { isTypingTarget } from "@/components/onboarding/spotlight";

/**
 * `T` opens and closes the Builder's test panel (#2074).
 *
 * Not while somebody is typing - the instructions are written on this page -
 * nor with a modifier held, which is the browser's or the OS's, nor while a
 * dialog is open over the Builder.
 */
export function useTestShortcut(enabled: boolean, toggle: () => void): void {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "t" && event.key !== "T") return;
      if (event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) return;
      if (isTypingTarget(event.target) || document.querySelector('[role="dialog"]')) return;
      event.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, toggle]);
}
