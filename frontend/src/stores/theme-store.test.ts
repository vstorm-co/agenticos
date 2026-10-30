import { afterEach, expect, it } from "vitest";
import { THEME_STORAGE_KEY } from "@/lib/appearance";
import { useThemeStore } from "./theme-store";

afterEach(async () => {
  localStorage.clear();
  delete window.__AGENTICOS_SHELL__;
  await useThemeStore.persist.rehydrate();
});

it("defaults to system theme and glass in desktop, including old settings without a look", async () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "test",
    window: "main",
    vibrancy: true,
  };
  for (const stored of [null, JSON.stringify({ state: { theme: "system" } })]) {
    if (stored === null) localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, stored);
    await useThemeStore.persist.rehydrate();
    expect(useThemeStore.getState()).toMatchObject({ theme: "system", look: "glass" });
  }
});

it("preserves an explicit user choice in desktop", async () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "test",
    window: "main",
    vibrancy: true,
  };
  localStorage.setItem(
    THEME_STORAGE_KEY,
    JSON.stringify({ state: { theme: "dark", look: "standard" } }),
  );
  await useThemeStore.persist.rehydrate();
  expect(useThemeStore.getState()).toMatchObject({ theme: "dark", look: "standard" });
});

it("keeps browser defaults and rejects invalid saved values", async () => {
  localStorage.setItem(
    THEME_STORAGE_KEY,
    JSON.stringify({ state: { theme: "invalid", look: false } }),
  );
  await useThemeStore.persist.rehydrate();
  expect(useThemeStore.getState()).toMatchObject({ theme: "system", look: "standard" });
});
