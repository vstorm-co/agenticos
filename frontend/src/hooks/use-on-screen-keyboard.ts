"use client";

import { useEffect } from "react";

/** The CSS variable the console's shell takes its height from. */
export const APP_HEIGHT = "--app-height";
/** The visual viewport may pan without scrolling the layout viewport. */
export const APP_TOP = "--app-top";
const KEYBOARD_TRANSITION_MS = 1000;
/** Set on `<html>` while somebody types on a touch keyboard. */
export const TYPING = "data-typing";

/** Whether focus landed somewhere a touch keyboard opens for. */
function opensAKeyboard(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable || target instanceof HTMLTextAreaElement) return true;
  return (
    target instanceof HTMLInputElement &&
    !["checkbox", "radio", "button", "submit", "range", "color", "file"].includes(target.type)
  );
}

/** Reveal the field and its controls using an existing internal scroller only. */
function revealWithinShell(field: HTMLElement, viewport: VisualViewport): void {
  const anchor = field.closest<HTMLElement>("[data-keyboard-anchor]") ?? field;
  for (
    let parent = anchor.parentElement;
    parent && parent !== document.body;
    parent = parent.parentElement
  ) {
    if (
      parent.scrollHeight <= parent.clientHeight ||
      !["auto", "scroll"].includes(getComputedStyle(parent).overflowY)
    )
      continue;
    const container = parent.getBoundingClientRect();
    const top = Math.max(container.top, viewport.offsetTop);
    const bottom = Math.min(container.bottom, viewport.offsetTop + viewport.height);
    const bounds = anchor.getBoundingClientRect();
    // An oversized editor still owns caret scrolling. Do not drag its enclosing
    // page back and forth trying to fit a rectangle that cannot fit.
    if (bounds.height > bottom - top) return;
    if (bounds.top < top) parent.scrollTop += bounds.top - top;
    else if (bounds.bottom > bottom) parent.scrollTop += bounds.bottom - bottom;
    return;
  }
}

/**
 * Make room for a phone's on-screen keyboard the way a messaging app does (#2066).
 *
 * **The shell is as tall as what can be seen.** Chrome on Android shrinks the
 * layout for the keyboard, which `interactive-widget` in the viewport asks for,
 * but Safari on iOS does not: the keyboard slides over the composer and Safari
 * scrolls the whole page up to reveal the field, header and all. The visual
 * viewport is the one measure every browser agrees on, so the shell's height
 * follows it, and the page that reveal scrolled is put back. Zoom is not a
 * keyboard: the height is measured in layout pixels, so pinching in leaves the
 * shell as tall as the window.
 *
 * **The tab bar steps aside while typing.** Left up, it sits on top of the
 * keyboard and takes a fifth of what is left of the screen; `data-typing` on
 * `<html>` is what the bar and the room kept for it read.
 */
export function useOnScreenKeyboard(): void {
  useEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let frame: number | null = null;
    let settleUntil: number | null = null;
    let revealed: { field: HTMLElement; height: number; top: number } | null = null;
    const touch = window.matchMedia?.("(pointer: coarse)").matches === true;
    const fit = () => {
      if (!viewport) return;
      // In layout pixels: a pinch-zoom (a trackpad's on a Mac, two fingers on a
      // phone) shrinks the visual viewport by its scale, and the shell followed
      // it - the console cut off at the height of the zoomed-in fragment. A
      // keyboard shrinks it at a scale of 1, so that still makes room.
      const height = `${Math.round(viewport.height * viewport.scale)}px`;
      if (root.style.getPropertyValue(APP_HEIGHT) !== height)
        root.style.setProperty(APP_HEIGHT, height);
      // Safari can pan only the visual viewport, leaving scrollY at zero.
      // Move the shell into that visible rectangle instead of repeatedly trying
      // to scroll a layout viewport which has not moved. Do not follow pinch zoom.
      const top = `${touch && viewport.scale === 1 ? viewport.offsetTop : 0}px`;
      if (root.style.getPropertyValue(APP_TOP) !== top) root.style.setProperty(APP_TOP, top);
      if (viewport.scale === 1 && window.scrollY !== 0) window.scrollTo(0, 0);
      // A short viewport can also overflow the shell's own scroll containers.
      // Reveal once per focus/viewport geometry, never repeat an impossible
      // correction for a field taller than the visible area on every frame.
      const active = document.activeElement;
      if (
        touch &&
        viewport.scale === 1 &&
        opensAKeyboard(active) &&
        active instanceof HTMLElement
      ) {
        if (
          revealed?.field !== active ||
          revealed.height !== viewport.height ||
          revealed.top !== viewport.offsetTop
        ) {
          revealed = { field: active, height: viewport.height, top: viewport.offsetTop };
          revealWithinShell(active, viewport);
        }
      } else revealed = null;
    };
    // Keyboard animations can report several viewport sizes per paint. Only
    // apply the latest one, avoiding repeated layout work in the same frame.
    const resized = () => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        fit();
        if (settleUntil !== null && performance.now() < settleUntil) resized();
        else settleUntil = null;
      });
    };
    // Some Safari versions update viewport geometry before delivering events.
    // Sample only during the bounded opening/closing transition, never on each
    // keystroke or for as long as an editor remains focused.
    const settle = () => {
      if (!viewport) return;
      settleUntil = performance.now() + KEYBOARD_TRANSITION_MS;
      fit();
      resized();
    };
    const focused = (event: FocusEvent) => {
      if (touch && opensAKeyboard(event.target)) {
        root.setAttribute(TYPING, "");
        settle();
      }
    };
    const blurred = () => {
      if (!root.hasAttribute(TYPING)) return;
      root.removeAttribute(TYPING);
      settle();
    };

    fit();
    viewport?.addEventListener("resize", resized);
    // iOS can reveal the old caret position after its resize event. The shell
    // already fits the keyboard then, so this late page pan must be undone too.
    viewport?.addEventListener("scroll", resized);
    window.addEventListener("scroll", resized, { passive: true });
    document.addEventListener("focusin", focused);
    document.addEventListener("focusout", blurred);
    return () => {
      viewport?.removeEventListener("resize", resized);
      viewport?.removeEventListener("scroll", resized);
      window.removeEventListener("scroll", resized);
      if (frame !== null) window.cancelAnimationFrame(frame);
      document.removeEventListener("focusin", focused);
      document.removeEventListener("focusout", blurred);
      root.style.removeProperty(APP_HEIGHT);
      root.style.removeProperty(APP_TOP);
      root.removeAttribute(TYPING);
    };
  }, []);
}
