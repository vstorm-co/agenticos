"use client";

import type { KeyboardEvent, MouseEvent, ReactNode, WheelEvent } from "react";
import { useTranslations } from "next-intl";

import type { BrowserCommand } from "@/hooks/use-live-browse";
import type { Browse } from "@/lib/browse";
import { cn } from "@/lib/utils";

/** The keys with no character that reach the page by name - `BrowserKey` on the server. */
const NAMED_KEYS = new Set([
  "Enter",
  "Tab",
  "Backspace",
  "Delete",
  "Escape",
  "ArrowUp",
  "ArrowDown",
  "ArrowLeft",
  "ArrowRight",
  "Home",
  "End",
  "PageUp",
  "PageDown",
]);

/**
 * The page as it is now, and - while this person holds the browser - the page itself.
 *
 * Holding, it takes the pointer and the keyboard the way a remote desktop does:
 * a click lands at the same point of the agent's viewport, scrolling scrolls it,
 * printable keys are typed and the named ones pressed. The picture is the
 * agent's own screenshot, so a click is mapped from where it fell on the picture
 * to the page's own pixels.
 */
export function LiveViewport({
  browse,
  holding,
  onCommand,
  flush = false,
  overlay,
}: {
  browse: Browse;
  holding: boolean;
  onCommand: (command: BrowserCommand) => void;
  /** Drawn inside a window that already frames it, so no frame of its own. */
  flush?: boolean;
  /** Drawn over the page, in its coordinates - the agent's cursor. */
  overlay?: ReactNode;
}) {
  const t = useTranslations("browse");
  // On the picture rather than the surface, because the point is measured
  // against the picture: it is drawn at whatever size the layout gives it.
  const onClick = (event: MouseEvent<HTMLImageElement>) => {
    if (!holding) return;
    const box = event.currentTarget.getBoundingClientRect();
    const scale = event.currentTarget.naturalWidth / box.width;
    onCommand({
      type: "click",
      x: Math.round((event.clientX - box.left) * scale),
      y: Math.round((event.clientY - box.top) * scale),
    });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!holding || event.metaKey || event.ctrlKey || event.altKey) return;
    if (NAMED_KEYS.has(event.key)) {
      event.preventDefault();
      onCommand({ type: "key", key: event.key });
    } else if (event.key.length === 1) {
      event.preventDefault();
      onCommand({ type: "type", text: event.key });
    }
  };

  const onWheel = (event: WheelEvent<HTMLDivElement>) => {
    if (holding) onCommand({ type: "scroll", dy: Math.round(event.deltaY) });
  };

  if (!browse.image) {
    return (
      <div className="bg-foreground/[0.03] text-muted-foreground flex aspect-[4/3] w-full items-center justify-center rounded-xl text-sm">
        {t("waiting")}
      </div>
    );
  }

  return (
    // A focusable surface rather than a button: it takes clicks at a point and
    // keys as text, which is what a remote screen is.
    <div
      role="application"
      aria-label={holding ? t("holdingLabel") : t("watchingLabel")}
      // A remote screen takes the keyboard while it is held, and keys reach only
      // what has focus.
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={holding ? 0 : -1}
      onKeyDown={onKeyDown}
      onPaste={(event) => {
        const text = event.clipboardData.getData("text");
        if (holding && text) onCommand({ type: "type", text });
      }}
      onWheel={onWheel}
      className={cn(
        "relative overflow-hidden outline-none",
        !flush && "rounded-xl",
        holding
          ? cn(
              "cursor-pointer ring-2 ring-sky-500 focus-visible:ring-sky-400",
              flush && "ring-inset",
            )
          : !flush && "ring-foreground/10 ring-1",
      )}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URL from
          the live view's socket, not a file the image pipeline can resolve. */}
      <img
        src={browse.image}
        alt={t("pageAlt")}
        className="block w-full select-none"
        draggable={false}
        onClick={onClick}
      />
      {overlay}
    </div>
  );
}
