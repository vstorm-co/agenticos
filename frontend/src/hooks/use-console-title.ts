"use client";

import { useEffect, type RefObject } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";
import { navSectionFor } from "@/lib/nav-sections";

/** Keep client-rendered console destinations identifiable in browser tabs and history. */
export function useConsoleTitle(main: RefObject<HTMLElement | null>): void {
  const pathname = usePathname();
  const t = useTranslations("nav");
  const { appName } = useBranding();
  const section = navSectionFor(pathname);
  const fallback = section ? t(section.item.labelKey) : appName;

  useEffect(() => {
    const content = main.current;
    if (!content) return;
    const update = () => {
      const headingElement = content.querySelector("h1");
      const heading = (headingElement?.innerText || headingElement?.textContent)
        ?.trim()
        .replace(/\s+/g, " ");
      const tab = content.querySelector('nav [aria-current="page"]')?.textContent?.trim();
      const parts = [...new Set([tab, heading].filter((part) => Boolean(part)))];
      const title = parts.length ? parts.join(" — ") : fallback;
      const resolved = title === appName ? appName : `${title} | ${appName}`;
      if (document.title !== resolved) document.title = resolved;
    };
    update();
    // Headings can arrive after the route's skeleton, or change after a rename.
    // Ignore streaming messages and other body mutations: they are not page titles.
    const relevant = (node: Node): boolean =>
      node instanceof Element &&
      Boolean(
        node.matches("h1, nav, title, [aria-current]") || node.querySelector("h1, nav, title"),
      );
    const observer = new MutationObserver((mutations) => {
      if (
        mutations.some(
          (mutation) =>
            (mutation.target instanceof Element
              ? mutation.target
              : mutation.target.parentElement
            )?.closest("h1, nav, title") ||
            [...mutation.addedNodes, ...mutation.removedNodes].some(relevant),
        )
      )
        update();
    });
    observer.observe(content, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["aria-current"],
    });
    // Next may stream the layout metadata after this client boundary hydrates.
    // Reconcile only title mutations; the equality guard prevents a write loop.
    observer.observe(document.head, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, [main, pathname, fallback, appName]);
}
