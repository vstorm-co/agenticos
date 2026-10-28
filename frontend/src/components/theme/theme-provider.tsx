"use client";

import { useEffect, useLayoutEffect } from "react";

import { usePathname } from "next/navigation";
import {
  DESKTOP_SETUP_ATTRIBUTE,
  isDesktopSetupPath,
  LOOK_ATTRIBUTE,
  THEME_STORAGE_KEY,
  type Look,
} from "@/lib/appearance";
import { setAppearance } from "@/lib/desktop/commands";
import { isDesktopShell, readShellInfo, reportShellFailure } from "@/lib/desktop/shell";
import { prefersReducedMotion } from "@/lib/motion";
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
 * View Transitions API, a reader who asked for reduced motion - at the operating
 * system or in their Motion preference - and a tab that is not on screen - the
 * system turning dark at dusk, or another tab changing the theme, while this one
 * is in the background. There the browser skips the transition and rejects its
 * `ready`, which surfaced as an unhandled error.
 */
function applyThemeAnimated(resolved: "light" | "dark") {
  const root = document.documentElement;
  if (root.classList.contains(resolved)) return;

  const firstPaint = !root.classList.contains("light") && !root.classList.contains("dark");
  const hidden = document.visibilityState !== "visible";
  if (
    firstPaint ||
    prefersReducedMotion() ||
    hidden ||
    document.startViewTransition === undefined
  ) {
    applyTheme(resolved);
    return;
  }
  const transition = document.startViewTransition(() => applyTheme(resolved));
  // A tab hidden mid-transition is skipped too. The theme is applied either way -
  // a skipped transition still runs its update - so only the sweep is lost.
  transition.ready.catch(() => undefined);
}

/** The standard look is the absence of the attribute, as the bootstrap script leaves it. */
function applyLook(look: Look) {
  const root = document.documentElement;
  if (look === "standard") root.removeAttribute(LOOK_ATTRIBUTE);
  else root.setAttribute(LOOK_ATTRIBUTE, look);
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const { theme, look } = useThemeStore();
  const setupPage = isDesktopSetupPath(usePathname());
  useLayoutEffect(() => {
    const shell = readShellInfo();
    document.documentElement.toggleAttribute(
      DESKTOP_SETUP_ATTRIBUTE,
      isDesktopShell(shell) && shell.window === "main" && setupPage,
    );
  }, [setupPage]);

  useEffect(() => {
    applyLook(look);
  }, [look]);

  // The desktop app's console window draws its material and its title bar in
  // the chosen mode, and builds itself that way on the next launch - so the
  // console window tells it. Blobby and quick ask follow; they do not lead.
  useEffect(() => {
    const shell = readShellInfo();
    if (!isDesktopShell(shell) || shell.window !== "main") return;
    setAppearance({ look, mode: theme }).catch((error: unknown) =>
      reportShellFailure("could not dress the window in the chosen appearance", error),
    );
  }, [look, theme, setupPage]);

  // Every window of the desktop app is a page of this origin with one
  // `localStorage`, and a choice made in the console has to reach blobby and
  // quick ask without a reload. The same holds for two browser tabs.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY) void useThemeStore.persist.rehydrate();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

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
