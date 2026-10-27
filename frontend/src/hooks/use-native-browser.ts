"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { getErrorMessage } from "@/lib/api-error";
import {
  controlNativeBrowser,
  nativeBrowserState,
  type NativeBrowserAction,
  type NativeBrowserState,
} from "@/lib/desktop/browser";
import { reportShellFailure } from "@/lib/desktop/shell";

/** Mount the live native renderer and join outstanding layout work before hiding it. */
export function useNativeBrowser(id: string) {
  const tErrors = useTranslations("errors");
  const viewport = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<NativeBrowserState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const send = useCallback(
    async (action: NativeBrowserAction, url?: string) => {
      try {
        await controlNativeBrowser(id, action, { url });
        setState(action === "close" ? null : await nativeBrowserState(id));
        setError(null);
        return true;
      } catch (reason) {
        setError(getErrorMessage(reason, tErrors, String(reason)));
        return false;
      }
    },
    [id, tErrors],
  );

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await nativeBrowserState(id);
        if (alive) {
          setState(next);
          setError(null);
        }
      } catch (reason) {
        if (alive) setError(getErrorMessage(reason, tErrors, String(reason)));
      }
      if (alive) timer = setTimeout(() => void poll(), 500);
    };
    void poll();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [id, tErrors]);

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const mount = crypto.randomUUID();
    let disposed = false;
    let queued = false;
    let sequence = Promise.resolve();
    const fit = () => {
      if (queued || disposed) return;
      queued = true;
      sequence = sequence
        .then(async () => {
          queued = false;
          if (disposed) return;
          const bounds = element.getBoundingClientRect();
          const blocked =
            document.visibilityState === "hidden" ||
            Boolean(
              document.querySelector(
                '[role="dialog"][data-state="open"],dialog[open],[data-native-browser-blocked]',
              ),
            );
          if (blocked || bounds.width < 1 || bounds.height < 1)
            await controlNativeBrowser(id, "hide", { mount });
          else
            await controlNativeBrowser(id, "show", {
              mount,
              bounds: { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height },
            });
        })
        .catch((reason) => {
          if (!disposed) setError(getErrorMessage(reason, tErrors, String(reason)));
        });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    const dialogs = new MutationObserver(fit);
    dialogs.observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["data-state", "open"],
    });
    window.addEventListener("resize", fit);
    window.addEventListener("scroll", fit, true);
    document.addEventListener("visibilitychange", fit);
    fit();
    return () => {
      disposed = true;
      observer.disconnect();
      dialogs.disconnect();
      window.removeEventListener("resize", fit);
      window.removeEventListener("scroll", fit, true);
      document.removeEventListener("visibilitychange", fit);
      void sequence
        .then(() => controlNativeBrowser(id, "hide", { mount }))
        .catch((reason) => reportShellFailure("could not hide the native browser", reason));
    };
  }, [id, tErrors]);
  return { viewport, state, error, send };
}
