"use client";

import { useEffect, useState } from "react";

import { useThemeStore } from "@/stores/theme-store";

/**
 * Dark or light, as the page is actually painted right now.
 *
 * `ThemeProvider` writes the answer onto `<html>` as a class, which is enough
 * for CSS and for any library that reads the DOM for it. It is not enough for
 * one that takes the colour mode as a *prop* and would otherwise ask
 * `prefers-color-scheme` itself: a reader who set the toggle to light on a dark
 * system would get an effect tuned for the wrong stage.
 *
 * Resolved here rather than read back off `document.documentElement`, so it is
 * a subscription rather than a poll, and so it re-renders when the system theme
 * changes under `system` - which is exactly the case the class alone handles
 * and a prop does not.
 */
export function useResolvedTheme(): "light" | "dark" {
  const theme = useThemeStore((state) => state.theme);
  // Light until the client says otherwise: `useEffect` does not run on the
  // server, and guessing dark there would flash the wrong one.
  const [system, setSystem] = useState<"light" | "dark">("light");

  useEffect(() => {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => setSystem(query.matches ? "dark" : "light");
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  return theme === "system" ? system : theme;
}
