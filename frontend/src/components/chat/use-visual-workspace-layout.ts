"use client";

import { useCallback, useLayoutEffect, useRef, useState, type RefObject } from "react";

/** Follow the reserved pane's bounds without moving the live iframe in the DOM. */
export function useVisualWorkspaceLayout(
  layer: RefObject<HTMLDivElement | null>,
  slot: HTMLElement | null,
  open: boolean,
  fullscreen: boolean,
  close: () => void,
) {
  const [bounds, setBounds] = useState<DOMRect | null>(null);
  const [inlineHeight, setInlineHeight] = useState(0);
  const opener = useRef<Element | null>(null);
  const dismiss = useCallback(() => {
    close();
    const element = opener.current;
    if (element instanceof HTMLElement && element.isConnected)
      element.focus({ preventScroll: true });
  }, [close]);
  useLayoutEffect(() => {
    const element = layer.current;
    if (!element) return;
    if (!open) {
      const measure = () => setInlineHeight(element.getBoundingClientRect().height);
      measure();
      const observer = new ResizeObserver(measure);
      observer.observe(element);
      return () => observer.disconnect();
    }
    const measure = () => {
      const rect = !fullscreen ? slot?.getBoundingClientRect() : undefined;
      const next = rect && rect.width > 0 && rect.height > 0 ? rect : null;
      setBounds((current) =>
        current &&
        next &&
        current.x === next.x &&
        current.y === next.y &&
        current.width === next.width &&
        current.height === next.height
          ? current
          : next,
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (slot) observer.observe(slot);
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [layer, slot, open, fullscreen]);

  useLayoutEffect(() => {
    const element = layer.current;
    if (!element || !open) return;
    opener.current = document.activeElement;
    // The top layer escapes the transcript's scrolling/mask without reparenting
    // an iframe, which would reload its document and discard all JavaScript state.
    element.showPopover();
    element.focus({ preventScroll: true });
    // A modal opened elsewhere in the product must not sit behind this layer.
    // Dialogs opened by the visual itself are portalled into it and stay open.
    const yieldToDialog = () => {
      const dialogs = document.querySelectorAll(
        '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]',
      );
      if (Array.from(dialogs).some((dialog) => !element.contains(dialog))) close();
    };
    const dialogs = new MutationObserver(yieldToDialog);
    dialogs.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-state"],
    });
    yieldToDialog();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target;
      if (target instanceof Element && target.closest('[role="menu"], [role="dialog"]')) return;
      event.preventDefault();
      dismiss();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      dialogs.disconnect();
      // Removing the attribute already closes the popover. React may do that
      // before cleanup, and hidePopover then throws on an ordinary inline node.
      if (element.isConnected && element.hasAttribute("popover")) element.hidePopover();
    };
  }, [layer, open, dismiss, close]);
  return { bounds, inlineHeight, dismiss };
}
