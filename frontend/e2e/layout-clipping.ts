/**
 * The clipping scan the Russian layout journey asserts on, run inside the page.
 *
 * A control is often not the element that clips: the sidebar keeps its label in a
 * shrinking `span.truncate` (`components/layout/app-sidebar.tsx`), and a Select
 * keeps its value in an inner span whose `text-overflow` is what turns a long
 * word into "Опубликов…" (`components/ui/select.tsx`). Measuring the control
 * alone reports nothing while the reader sees an ellipsis, so the scan measures
 * the control and every text-bearing descendant that clips.
 *
 * Playwright serialises this function into the page, so it must not close over
 * anything in this module: every constant lives inside the body.
 */
export interface ClippingReport {
  /** One entry per clipped label, as `<selector path>: <text>`. */
  clipped: string[];
  /** How far the document scrolls sideways, which `truncate` alone does not cause. */
  overflow: number;
}

export function scanClippedText(selector: string): ClippingReport {
  const CYRILLIC = /[А-Яа-яЁё]/;

  /** A short path from the control down to the element, for the report. */
  function describe(element: Element): string {
    const parts: string[] = [];
    let node: Element | null = element;
    while (node && node !== document.body && parts.length < 4) {
      const tag = node.tagName.toLowerCase();
      const slot = node.getAttribute("data-slot");
      const role = node.getAttribute("role");
      const marker = slot ? `[data-slot="${slot}"]` : role ? `[role="${role}"]` : "";
      // One plain class token, not the whole Tailwind list: `span.truncate` says
      // where the ellipsis lives, four utility classes say nothing a reader wants.
      const name = (node.getAttribute("class") ?? "")
        .split(/\s+/)
        .find((token) => /^[a-z][a-z0-9-]*$/.test(token));
      parts.unshift(`${tag}${marker}${name ? `.${name}` : ""}`);
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  function measure(element: HTMLElement, clipped: string[]): void {
    const text = element.innerText?.trim() ?? "";
    if (!CYRILLIC.test(text)) return;
    const rect = element.getBoundingClientRect();
    // A screen-reader-only label (`sr-only`) is a 1px box clipped on purpose: it
    // is read aloud, never seen, so nothing a reader sees is cut.
    if (rect.width <= 1 || rect.height <= 1) return;
    const style = getComputedStyle(element);
    const clips =
      style.overflowX === "hidden" ||
      style.overflowX === "clip" ||
      style.overflowY === "hidden" ||
      style.overflowY === "clip" ||
      style.textOverflow === "ellipsis" ||
      style.webkitLineClamp !== "none";
    const cut =
      element.scrollWidth > element.clientWidth + 1 ||
      element.scrollHeight > element.clientHeight + 1;
    if (clips && cut) clipped.push(`${describe(element)}: ${text}`);
  }

  /** Whether this element holds words of its own, rather than only other elements. */
  function ownsText(element: Element): boolean {
    return Array.from(element.childNodes).some(
      (node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "",
    );
  }

  const clipped: string[] = [];
  for (const control of document.querySelectorAll<HTMLElement>(selector)) {
    measure(control, clipped);
    for (const descendant of control.querySelectorAll<HTMLElement>("*")) {
      if (ownsText(descendant)) measure(descendant, clipped);
    }
  }

  return {
    clipped: [...new Set(clipped)],
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}
