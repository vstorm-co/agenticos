import { afterEach, describe, expect, it } from "vitest";

import {
  APPEARANCE_BOOTSTRAP_SCRIPT,
  DESKTOP_SETUP_ATTRIBUTE,
  isLook,
  LOOK_ATTRIBUTE,
  SHELL_ATTRIBUTE,
  SHELL_WINDOW_ATTRIBUTE,
  THEME_STORAGE_KEY,
  VIBRANCY_ATTRIBUTE,
} from "./appearance";

/** Run the pre-paint script as the browser would, inline, against this document. */
function boot() {
  new Function(APPEARANCE_BOOTSTRAP_SCRIPT)();
}

const root = () => document.documentElement;

declare global {
  interface Window {
    AgenticOSInsets?: { top: () => number; bottom: () => number };
  }
}

afterEach(() => {
  localStorage.clear();
  window.history.replaceState(null, "", "/");
  root().removeAttribute(DESKTOP_SETUP_ATTRIBUTE);
  delete window.__AGENTICOS_SHELL__;
  delete window.AgenticOSInsets;
  root().style.removeProperty("--shell-inset-top");
  root().style.removeProperty("--shell-inset-bottom");
  for (const attribute of [
    LOOK_ATTRIBUTE,
    SHELL_ATTRIBUTE,
    SHELL_WINDOW_ATTRIBUTE,
    VIBRANCY_ATTRIBUTE,
  ]) {
    root().removeAttribute(attribute);
  }
});

describe("isLook", () => {
  it("knows the five looks and nothing else", () => {
    expect(isLook("glass")).toBe(true);
    expect(isLook("standard")).toBe(true);
    expect(isLook("neon")).toBe(false);
    expect(isLook(3)).toBe(false);
  });
});

describe("the appearance bootstrap", () => {
  it("puts the stored look on <html> before the theme provider runs", () => {
    localStorage.setItem(
      THEME_STORAGE_KEY,
      JSON.stringify({ state: { theme: "dark", look: "midnight" } }),
    );
    boot();
    expect(root().getAttribute(LOOK_ATTRIBUTE)).toBe("midnight");
  });

  it("leaves the standard look, an unknown one and an empty store as no attribute", () => {
    for (const stored of [{ state: { look: "standard" } }, { state: { look: "neon" } }, {}]) {
      localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(stored));
      boot();
      expect(root().hasAttribute(LOOK_ATTRIBUTE)).toBe(false);
    }
  });

  it("survives a store that does not parse", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "{not json");
    expect(boot).not.toThrow();
    expect(root().hasAttribute(LOOK_ATTRIBUTE)).toBe(false);
  });

  it("marks the page as the desktop app's, its window, and a window with a material", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "macos",
      version: "0.2.0",
      window: "main",
      vibrancy: true,
    };
    boot();
    expect(root().getAttribute(SHELL_ATTRIBUTE)).toBe("macos");
    expect(root().getAttribute(SHELL_WINDOW_ATTRIBUTE)).toBe("main");
    expect(root().hasAttribute(VIBRANCY_ATTRIBUTE)).toBe(true);
  });

  it("draws no material where the window has none, and nothing at all in a browser", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "linux",
      version: "0.2.0",
      window: "blobby",
      vibrancy: false,
    };
    boot();
    expect(root().getAttribute(SHELL_ATTRIBUTE)).toBe("linux");
    expect(root().hasAttribute(VIBRANCY_ATTRIBUTE)).toBe(false);

    root().removeAttribute(SHELL_ATTRIBUTE);
    delete window.__AGENTICOS_SHELL__;
    boot();
    expect(root().hasAttribute(SHELL_ATTRIBUTE)).toBe(false);
  });

  it("keeps the room the Android app measured for its status and gesture bars, and its own when it measured none", () => {
    window.__AGENTICOS_SHELL__ = {
      platform: "android",
      version: "0.1.0",
      window: "main",
      vibrancy: false,
    };
    window.AgenticOSInsets = { top: () => 42, bottom: () => 24 };
    boot();
    expect(root().style.getPropertyValue("--shell-inset-top")).toBe("42px");
    expect(root().style.getPropertyValue("--shell-inset-bottom")).toBe("24px");

    root().style.removeProperty("--shell-inset-top");
    window.AgenticOSInsets = { top: () => 0, bottom: () => 0 };
    boot();
    expect(root().style.getPropertyValue("--shell-inset-top")).toBe("");

    window.AgenticOSInsets = {
      top: () => {
        throw new Error("gone");
      },
      bottom: () => 0,
    };
    expect(() => boot()).not.toThrow();
  });
});

it("starts desktop glass before paint but respects an explicitly saved standard look", () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    version: "test",
    window: "main",
    vibrancy: true,
  };
  boot();
  expect(root().getAttribute(LOOK_ATTRIBUTE)).toBe("glass");
  root().removeAttribute(LOOK_ATTRIBUTE);
  localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ state: { look: "standard" } }));
  boot();
  expect(root().hasAttribute(LOOK_ATTRIBUTE)).toBe(false);
});

it("marks connection setup before paint even when the console preference is opaque", () => {
  window.__AGENTICOS_SHELL__ = {
    platform: "macos",
    window: "main",
    version: "test",
    vibrancy: true,
  };
  localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ state: { look: "standard" } }));
  window.history.replaceState(null, "", "/pl/desktop/readiness?connection=1");
  boot();
  expect(root()).toHaveAttribute(DESKTOP_SETUP_ATTRIBUTE);
  expect(root().hasAttribute(LOOK_ATTRIBUTE)).toBe(false);
});
