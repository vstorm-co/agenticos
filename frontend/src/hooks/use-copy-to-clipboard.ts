"use client";

import { useEffect, useRef, useState } from "react";

export function useCopyToClipboard(resetMs = 2000) {
  const [copied, setCopied] = useState(false);
  const reset = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTimeout(reset.current);
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
      // The write can settle after the component that asked for it is gone.
      if (!mounted.current) return true;
      setCopied(true);
      clearTimeout(reset.current);
      reset.current = setTimeout(() => setCopied(false), resetMs);
      return true;
    } catch {
      return false;
    }
  };

  return { copy, copied };
}
