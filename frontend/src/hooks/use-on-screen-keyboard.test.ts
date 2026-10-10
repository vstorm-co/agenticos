import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { APP_HEIGHT, TYPING, useOnScreenKeyboard } from "./use-on-screen-keyboard";

class FakeViewport extends EventTarget {
  height = 800;
}

let viewport: FakeViewport;
let coarse = true;
const root = document.documentElement;

beforeEach(() => {
  viewport = new FakeViewport();
  coarse = true;
  vi.stubGlobal("visualViewport", viewport);
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: coarse, media: query }));
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

function focus(html: string) {
  document.body.innerHTML = html;
  const element = document.body.firstElementChild as HTMLElement;
  element.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
  return element;
}

describe("useOnScreenKeyboard", () => {
  it("keeps the shell as tall as what can be seen, and puts a scrolled page back", () => {
    renderHook(() => useOnScreenKeyboard());
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("800px");

    viewport.height = 420;
    vi.stubGlobal("scrollY", 300);
    viewport.dispatchEvent(new Event("resize"));

    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("420px");
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("leaves a page that did not scroll alone", () => {
    vi.stubGlobal("scrollY", 0);
    renderHook(() => useOnScreenKeyboard());

    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("marks typing on a touch keyboard, for every kind of field that opens one", () => {
    renderHook(() => useOnScreenKeyboard());

    for (const field of [
      "<textarea></textarea>",
      '<input type="text" />',
      '<div contenteditable="true"></div>',
    ]) {
      const element = focus(field);
      if (element.getAttribute("contenteditable")) {
        Object.defineProperty(element, "isContentEditable", { value: true });
        element.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
      }
      expect(root.hasAttribute(TYPING)).toBe(true);
      element.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
      expect(root.hasAttribute(TYPING)).toBe(false);
    }
  });

  it("does not for a control that opens no keyboard, or anything off a page", () => {
    renderHook(() => useOnScreenKeyboard());

    focus('<input type="checkbox" />');
    focus("<button>Go</button>");
    document.dispatchEvent(new FocusEvent("focusin"));

    expect(root.hasAttribute(TYPING)).toBe(false);
  });

  it("does not with a mouse and a real keyboard", () => {
    coarse = false;
    renderHook(() => useOnScreenKeyboard());

    focus("<textarea></textarea>");

    expect(root.hasAttribute(TYPING)).toBe(false);
  });

  it("still marks typing where the browser has no visual viewport, and cleans up after itself", () => {
    vi.stubGlobal("visualViewport", null);
    const { unmount } = renderHook(() => useOnScreenKeyboard());
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("");

    focus("<textarea></textarea>");
    expect(root.hasAttribute(TYPING)).toBe(true);

    unmount();
    expect(root.hasAttribute(TYPING)).toBe(false);
  });
});
