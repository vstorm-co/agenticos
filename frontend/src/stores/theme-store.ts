"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { readShellInfo } from "@/lib/desktop/shell";
import { defaultLook, isLook, THEME_STORAGE_KEY, type Look } from "@/lib/appearance";

export type Theme = "light" | "dark" | "system";

interface ThemeState {
  theme: Theme;
  /** Local deliberate edits; remote adoption does not enqueue another write. */
  editRevision: number;
  editedField: "theme" | "look" | null;
  /** The console's style, orthogonal to light and dark (`lib/appearance.ts`). */
  look: Look;
  setTheme: (theme: Theme) => void;
  setLook: (look: Look) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "system",
      editRevision: 0,
      editedField: null,
      look: "standard",
      setTheme: (theme) =>
        set((state) => ({ theme, editedField: "theme", editRevision: state.editRevision + 1 })),
      setLook: (look) =>
        set((state) => ({ look, editedField: "look", editRevision: state.editRevision + 1 })),
    }),
    {
      // The key `APPEARANCE_BOOTSTRAP_SCRIPT` reads the look from before the
      // first paint, which is why it is a shared constant and not a literal.
      name: THEME_STORAGE_KEY,
      partialize: ({ theme, look }) => ({ theme, look }),
      merge: (persisted: unknown, current) => {
        const saved = persisted !== null && typeof persisted === "object" ? persisted : {};
        const theme = "theme" in saved ? saved.theme : undefined;
        const look = "look" in saved ? saved.look : undefined;
        return {
          ...current,
          theme: theme === "light" || theme === "dark" || theme === "system" ? theme : "system",
          look: isLook(look) ? look : defaultLook(readShellInfo()?.platform),
        };
      },
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
