"use client";

import { useEffect, useRef, useState } from "react";

function copyPlainText(text: string): boolean {
  if (typeof document.execCommand !== "function") return false;
  const focused = document.activeElement;
  // Keep the selection inside a modal's focus trap, including on plain HTTP.
  const container = focused?.closest('[role="dialog"], [role="alertdialog"]') ?? document.body;
  const field = document.createElement("textarea");
  field.value = text;
  field.readOnly = true;
  field.tabIndex = -1;
  field.style.cssText = "position:fixed;inset:0 auto auto 0;opacity:0";
  container.append(field);
  try {
    field.focus({ preventScroll: true });
    field.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
    if (focused instanceof HTMLElement) focused.focus({ preventScroll: true });
  }
}

export function useCopyToClipboard(resetMs = 2000) {
  const [copied, setCopied] = useState(false);
  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (timer.current !== null) clearTimeout(timer.current);
    };
  }, []);

  /**
   * Copy `text`, and `html` beside it when there is a richer form to offer.
   *
   * Both go on the clipboard as one item, so the destination picks: a
   * spreadsheet takes the HTML, a text field the plain text. A browser with no
   * `ClipboardItem` gets the plain text alone, which is still the whole content.
   */
  const copy = async (text: string, html?: string): Promise<boolean> => {
    try {
      const clipboard = navigator.clipboard;
      if (html !== undefined && typeof ClipboardItem !== "undefined" && clipboard?.write) {
        await clipboard.write([
          new ClipboardItem({
            "text/plain": new Blob([text], { type: "text/plain" }),
            "text/html": new Blob([html], { type: "text/html" }),
          }),
        ]);
      } else {
        if (!clipboard?.writeText) {
          if (!copyPlainText(text)) return false;
        } else {
          await clipboard.writeText(text);
        }
      }
    } catch {
      if (!copyPlainText(text)) return false;
    }
    if (!mounted.current) return true;
    setCopied(true);
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      setCopied(false);
    }, resetMs);
    return true;
  };

  return { copy, copied };
}
