"use client";

import { useEffect } from "react";
import { useThemeStore, getResolvedTheme } from "@/stores/theme-store";

interface ThemeProviderProps {
  children: React.ReactNode;
}

function applyTheme(resolved: "light" | "dark") {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  root.classList.add(resolved);
  root.style.colorScheme = resolved;
}

/**
 * Apply the theme inside a view transition, so the change sweeps across the
 * screen from the bottom-left corner instead of flipping every pixel at once -
 * the clip-path animation lives on `::view-transition-new(root)` in
 * `globals.css`.
 *
 * Four cases go without the sweep, each for its own reason: the first paint
 * (there is no previous theme on the root to sweep away from - animating it
 * would wipe the page against itself on every load), a browser without the
 * View Transitions API, a reader who asked for reduced motion, and a tab that is
 * not on screen - the system turning dark at dusk, or another tab changing the
 * theme, while this one is in the background. There the browser skips the
 * transition and rejects its `ready`, which surfaced as an unhandled error.
 */
function applyThemeAnimated(resolved: "light" | "dark") {
  const root = document.documentElement;
  if (root.classList.contains(resolved)) return;

  const firstPaint = !root.classList.contains("light") && !root.classList.contains("dark");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hidden = document.visibilityState !== "visible";
  if (firstPaint || reducedMotion || hidden || document.startViewTransition === undefined) {
    applyTheme(resolved);
    return;
  }
  const transition = document.startViewTransition(() => applyTheme(resolved));
  // A tab hidden mid-transition is skipped too. The theme is applied either way -
  // a skipped transition still runs its update - so only the sweep is lost.
  transition.ready.catch(() => undefined);
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const { theme } = useThemeStore();

  useEffect(() => {
    applyThemeAnimated(getResolvedTheme(theme));
  }, [theme]);

  useEffect(() => {
    if (theme !== "system") return;

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const handleChange = () => {
      applyThemeAnimated(mediaQuery.matches ? "dark" : "light");
    };

    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, [theme]);

  return <>{children}</>;
}
