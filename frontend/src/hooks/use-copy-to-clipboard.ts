"use client";

import { useEffect, useRef, useState } from "react";

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
      if (html !== undefined && typeof ClipboardItem !== "undefined") {
        await navigator.clipboard.write([
          new ClipboardItem({
            "text/plain": new Blob([text], { type: "text/plain" }),
            "text/html": new Blob([html], { type: "text/html" }),
          }),
        ]);
      } else {
        await navigator.clipboard.writeText(text);
      }
      if (!mounted.current) return true;
      setCopied(true);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        timer.current = null;
        setCopied(false);
      }, resetMs);
      return true;
    } catch {
      return false;
    }
  };

  return { copy, copied };
}
