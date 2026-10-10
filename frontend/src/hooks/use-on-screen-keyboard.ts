"use client";

import { useEffect } from "react";

/** The CSS variable the console's shell takes its height from. */
export const APP_HEIGHT = "--app-height";
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

/**
 * Make room for a phone's on-screen keyboard the way a messaging app does (#2066).
 *
 * **The shell is as tall as what can be seen.** Chrome on Android shrinks the
 * layout for the keyboard, which `interactive-widget` in the viewport asks for,
 * but Safari on iOS does not: the keyboard slides over the composer and Safari
 * scrolls the whole page up to reveal the field, header and all. The visual
 * viewport is the one measure every browser agrees on, so the shell's height
 * follows it, and the page that reveal scrolled is put back.
 *
 * **The tab bar steps aside while typing.** Left up, it sits on top of the
 * keyboard and takes a fifth of what is left of the screen; `data-typing` on
 * `<html>` is what the bar and the room kept for it read.
 */
export function useOnScreenKeyboard(): void {
  useEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    const fit = () => {
      if (!viewport) return;
      root.style.setProperty(APP_HEIGHT, `${viewport.height}px`);
      if (window.scrollY !== 0) window.scrollTo(0, 0);
    };
    const touch = window.matchMedia?.("(pointer: coarse)").matches === true;
    const focused = (event: FocusEvent) => {
      if (touch && opensAKeyboard(event.target)) root.setAttribute(TYPING, "");
    };
    const blurred = () => root.removeAttribute(TYPING);

    fit();
    viewport?.addEventListener("resize", fit);
    document.addEventListener("focusin", focused);
    document.addEventListener("focusout", blurred);
    return () => {
      viewport?.removeEventListener("resize", fit);
      document.removeEventListener("focusin", focused);
      document.removeEventListener("focusout", blurred);
      root.style.removeProperty(APP_HEIGHT);
      root.removeAttribute(TYPING);
    };
  }, []);
}
