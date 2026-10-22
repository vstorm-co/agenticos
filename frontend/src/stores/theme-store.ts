"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { THEME_STORAGE_KEY, type Look } from "@/lib/appearance";

export type Theme = "light" | "dark" | "system";

interface ThemeState {
  theme: Theme;
  /** The console's style, orthogonal to light and dark (`lib/appearance.ts`). */
  look: Look;
  setTheme: (theme: Theme) => void;
  setLook: (look: Look) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "system",
      look: "standard",
      setTheme: (theme) => set({ theme }),
      setLook: (look) => set({ look }),
    }),
    {
      // The key `APPEARANCE_BOOTSTRAP_SCRIPT` reads the look from before the
      // first paint, which is why it is a shared constant and not a literal.
      name: THEME_STORAGE_KEY,
    },
  ),
);

/**
 * Get the resolved theme (light or dark) based on the current theme setting.
 * When theme is "system", it checks the user's system preference.
 */
export function getResolvedTheme(theme: Theme): "light" | "dark" {
  if (theme === "system") {
    if (typeof window !== "undefined") {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    return "light";
  }
  return theme;
}
