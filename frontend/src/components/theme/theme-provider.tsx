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
 * Three cases go without the sweep, each for its own reason: the first paint
 * (there is no previous theme on the root to sweep away from - animating it
 * would wipe the page against itself on every load), a browser without the
 * View Transitions API, and a reader who asked for reduced motion.
 */
function applyThemeAnimated(resolved: "light" | "dark") {
  const root = document.documentElement;
  if (root.classList.contains(resolved)) return;

  const firstPaint = !root.classList.contains("light") && !root.classList.contains("dark");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (firstPaint || reducedMotion || document.startViewTransition === undefined) {
    applyTheme(resolved);
    return;
  }
  document.startViewTransition(() => applyTheme(resolved));
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
