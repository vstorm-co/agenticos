import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { APP_HEIGHT, APP_TOP, TYPING, useOnScreenKeyboard } from "./use-on-screen-keyboard";

class FakeViewport extends EventTarget {
  height = 800;
  scale = 1;
  offsetTop = 0;
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
  vi.useFakeTimers();
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    window.setTimeout(() => callback(0), 16),
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
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
    vi.advanceTimersByTime(16);

    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("420px");
    expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
  });

  it("keeps the shell as tall as the window while the page is pinch-zoomed", () => {
    // A trackpad pinch on a Mac shrank the shell to the zoomed-in fragment, and
    // the rest of the window stood empty under it.
    renderHook(() => useOnScreenKeyboard());

    viewport.height = 400;
    viewport.scale = 2;
    viewport.offsetTop = 100;
    vi.stubGlobal("scrollY", 300);
    viewport.dispatchEvent(new Event("resize"));
    vi.advanceTimersByTime(16);

    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("800px");
    // Panning a zoomed page is the reader's, not a keyboard's reveal to undo.
    expect(window.scrollTo).not.toHaveBeenCalled();
    expect(root.style.getPropertyValue(APP_TOP)).toBe("0px");
  });

  it("follows a visual-only reveal without relying on window scroll", () => {
    renderHook(() => useOnScreenKeyboard());
    viewport.height = 420;
    viewport.offsetTop = 70;
    vi.stubGlobal("scrollY", 0);
    viewport.dispatchEvent(new Event("scroll"));
    vi.advanceTimersByTime(16);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("420px");
    expect(root.style.getPropertyValue(APP_TOP)).toBe("70px");
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("uses offsetTop independently of document scrolling", () => {
    renderHook(() => useOnScreenKeyboard());
    viewport.offsetTop = 70;
    vi.stubGlobal("scrollY", 280);
    viewport.dispatchEvent(new Event("scroll"));
    vi.advanceTimersByTime(16);
    expect(root.style.getPropertyValue(APP_TOP)).toBe("70px");
    expect(window.scrollTo).toHaveBeenCalledExactlyOnceWith(0, 0);
  });

  it("measures opening and closing before delayed viewport events arrive", () => {
    renderHook(() => useOnScreenKeyboard());
    const editor = focus("<textarea></textarea>");
    vi.advanceTimersByTime(300);
    viewport.height = 420;
    viewport.offsetTop = 70;
    vi.advanceTimersByTime(16);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("420px");
    expect(root.style.getPropertyValue(APP_TOP)).toBe("70px");
    vi.advanceTimersByTime(1100);
    expect(vi.getTimerCount()).toBe(0);
    editor.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    viewport.height = 800;
    viewport.offsetTop = 0;
    vi.advanceTimersByTime(16);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("800px");
    expect(root.style.getPropertyValue(APP_TOP)).toBe("0px");
    vi.advanceTimersByTime(1100);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([true, false])(
    "reveals controls in their own scroller once per geometry (anchor=%s)",
    (anchored) => {
      renderHook(() => useOnScreenKeyboard());
      document.body.innerHTML = `<div style="overflow-y:auto">${anchored ? "<div data-keyboard-anchor><textarea></textarea></div>" : "<textarea></textarea>"}</div>`;
      const scroller = document.body.firstElementChild;
      const editor = document.querySelector("textarea");
      if (!(scroller instanceof HTMLElement) || !editor)
        throw new Error("Expected the scroll fixture");
      const anchor = anchored ? editor.parentElement : editor;
      if (!anchor) throw new Error("Expected the control region");
      Object.defineProperties(scroller, {
        clientHeight: { value: 420 },
        scrollHeight: { value: 1200 },
      });
      vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 70, 390, 420));
      const bounds = vi.spyOn(anchor, "getBoundingClientRect");
      bounds.mockReturnValue(new DOMRect(0, 600, 390, 180));
      editor.focus();
      expect(scroller.scrollTop).toBe(290);
      vi.advanceTimersByTime(300);
      expect(scroller.scrollTop).toBe(290);
      viewport.height = 420;
      viewport.offsetTop = 70;
      bounds.mockReturnValue(new DOMRect(0, 20, 390, 180));
      vi.advanceTimersByTime(16);
      expect(scroller.scrollTop).toBe(240);
      vi.advanceTimersByTime(300);
      expect(scroller.scrollTop).toBe(240);
      expect(window.scrollTo).not.toHaveBeenCalled();
    },
  );

  it("skips clipped ancestors and leaves a fully visible field in place", () => {
    renderHook(() => useOnScreenKeyboard());
    document.body.innerHTML =
      '<div style="overflow-y:auto"><div style="overflow-y:hidden"><textarea></textarea></div></div>';
    const outer = document.body.firstElementChild;
    const inner = outer?.firstElementChild;
    const editor = document.querySelector("textarea");
    if (!(outer instanceof HTMLElement) || !(inner instanceof HTMLElement) || !editor)
      throw new Error("Expected the nested scroll fixture");
    for (const element of [outer, inner])
      Object.defineProperties(element, {
        clientHeight: { value: 420 },
        scrollHeight: { value: 1200 },
      });
    vi.spyOn(outer, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 390, 420));
    vi.spyOn(editor, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 100, 390, 180));
    editor.focus();
    vi.advanceTimersByTime(1100);
    expect(outer.scrollTop).toBe(0);
    expect(inner.scrollTop).toBe(0);
  });

  it("leaves oversized editors to caret scrolling without a repeated correction", () => {
    renderHook(() => useOnScreenKeyboard());
    document.body.innerHTML = '<div style="overflow-y:scroll"><textarea></textarea></div>';
    const scroller = document.body.firstElementChild;
    const editor = document.querySelector("textarea");
    if (!(scroller instanceof HTMLElement) || !editor)
      throw new Error("Expected the scroll fixture");
    Object.defineProperties(scroller, {
      clientHeight: { value: 420 },
      scrollHeight: { value: 1200 },
    });
    vi.spyOn(scroller, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 390, 420));
    vi.spyOn(editor, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 20, 390, 800));
    editor.focus();
    vi.advanceTimersByTime(1100);
    expect(scroller.scrollTop).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels focus settling on unmount and stops all future measurements", () => {
    const { unmount } = renderHook(() => useOnScreenKeyboard());
    focus("<textarea></textarea>");
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    viewport.height = 420;
    viewport.dispatchEvent(new Event("resize"));
    window.dispatchEvent(new Event("scroll"));
    focus("<textarea></textarea>");
    vi.advanceTimersByTime(1100);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("");
    expect(root.style.getPropertyValue(APP_TOP)).toBe("");
    expect(root.hasAttribute(TYPING)).toBe(false);
  });

  it("coalesces keyboard animation events and ignores unchanged sizes", () => {
    const write = vi.spyOn(root.style, "setProperty");
    renderHook(() => useOnScreenKeyboard());
    write.mockClear();
    for (let height = 700; height >= 400; height -= 10) {
      viewport.height = height;
      viewport.dispatchEvent(new Event("resize"));
    }
    expect(write).not.toHaveBeenCalled();
    vi.advanceTimersByTime(16);
    expect(write).toHaveBeenCalledTimes(1);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("400px");
    viewport.dispatchEvent(new Event("resize"));
    vi.advanceTimersByTime(16);
    expect(write).toHaveBeenCalledTimes(1);
    write.mockRestore();
  });

  it("cancels a queued viewport update when unmounted", () => {
    const { unmount } = renderHook(() => useOnScreenKeyboard());
    viewport.height = 400;
    viewport.dispatchEvent(new Event("resize"));
    unmount();
    vi.advanceTimersByTime(16);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("");
  });

  it("undoes iOS's late reveal scroll after the keyboard resize has finished", () => {
    renderHook(() => useOnScreenKeyboard());
    viewport.height = 400;
    viewport.dispatchEvent(new Event("resize"));
    vi.advanceTimersByTime(16);
    vi.stubGlobal("scrollY", 280);
    viewport.dispatchEvent(new Event("scroll"));
    window.dispatchEvent(new Event("scroll"));
    vi.advanceTimersByTime(16);
    expect(window.scrollTo).toHaveBeenCalledExactlyOnceWith(0, 0);
    expect(root.style.getPropertyValue(APP_HEIGHT)).toBe("400px");
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

    const checkbox = focus('<input type="checkbox" />');
    checkbox.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    focus("<button>Go</button>");
    document.dispatchEvent(new FocusEvent("focusin"));

    expect(root.hasAttribute(TYPING)).toBe(false);
  });

  it("does not with a mouse and a real keyboard", () => {
    coarse = false;
    renderHook(() => useOnScreenKeyboard());

    focus("<textarea></textarea>");

    expect(root.hasAttribute(TYPING)).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
    viewport.offsetTop = 70;
    viewport.dispatchEvent(new Event("scroll"));
    vi.advanceTimersByTime(16);
    expect(root.style.getPropertyValue(APP_TOP)).toBe("0px");
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
