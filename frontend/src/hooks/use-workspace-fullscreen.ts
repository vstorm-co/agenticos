"use client";

import { useEffect, useRef, useState } from "react";

/** Expand in place: editors keep their DOM and unsaved input while the shell steps aside. */
export function useWorkspaceFullscreen(initialExpanded = false) {
  const ref = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(initialExpanded);
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 768px)");
    const collapseOnDesktop = () => {
      if (desktop.matches) setExpanded(false);
    };
    desktop.addEventListener("change", collapseOnDesktop);
    return () => desktop.removeEventListener("change", collapseOnDesktop);
  }, []);
  useEffect(() => {
    if (!expanded || ref.current === null) return;
    const focused = document.activeElement;
    if (!(focused instanceof HTMLElement) || !ref.current.contains(focused)) {
      const target = ref.current.querySelector<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex="0"]',
      );
      target?.focus();
    }
    const previous: { element: HTMLElement; inert: boolean; visibility: string }[] = [];
    let current: HTMLElement = ref.current;
    while (current.parentElement !== null) {
      for (const sibling of current.parentElement.children) {
        if (sibling instanceof HTMLElement && sibling !== current) {
          previous.push({
            element: sibling,
            inert: Boolean(sibling.inert),
            visibility: sibling.style.visibility,
          });
          sibling.style.visibility = "hidden";
          sibling.inert = true;
        }
      }
      current = current.parentElement;
    }
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // A menu or record panel owns its first Escape.
      if (
        document.querySelector(
          '[data-state="open"][role="dialog"], [data-state="open"][role="menu"]',
        )
      )
        return;
      setExpanded(false);
    };
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("keydown", escape);
      document.body.style.overflow = overflow;
      for (const { element, inert, visibility } of previous) {
        element.inert = inert;
        element.style.visibility = visibility;
      }
      if (focused instanceof HTMLElement && focused.isConnected && !focused.closest("[inert]")) {
        focused.focus();
      }
    };
  }, [expanded]);
  return { ref, expanded, toggle: () => setExpanded((value) => !value) };
}
