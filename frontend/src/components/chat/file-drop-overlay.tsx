"use client";

import { createPortal } from "react-dom";
import { Upload } from "lucide-react";
import { useTranslations } from "next-intl";

interface FileDropOverlayProps {
  /** Something is being dragged over the page right now. */
  active: boolean;
  /** The per-file limit, so the answer is on screen before the file is dropped. */
  maxSizeMb: number;
}

/**
 * The whole page as a drop target, for as long as a file is over it.
 *
 * Drawn across the viewport rather than around the composer, because the point
 * is that there is nothing to aim at: the target used to be a strip a few
 * centimetres tall, and everywhere else was a navigation away from the
 * conversation.
 *
 * Portalled to the body rather than positioned from here. `fixed` is measured
 * against the nearest ancestor with a transform or a filter rather than against
 * the viewport, and this renders from inside the composer - one `backdrop-blur`
 * on a wrapper anywhere above it would silently shrink the overlay back to a
 * corner of the screen.
 *
 * Hidden from assistive technology, and that is not an oversight: a drag is a
 * pointer gesture nobody can perform from a keyboard, so this can only ever be
 * noise to a screen reader. The button beside the composer is the accessible
 * route to the same thing.
 */
export function FileDropOverlay({ active, maxSizeMb }: FileDropOverlayProps) {
  const t = useTranslations("chat.input");
  if (!active) return null;

  return createPortal(
    <div
      aria-hidden
      data-testid="file-drop-overlay"
      className="bg-background/70 fixed inset-0 z-50 flex items-center justify-center p-6 backdrop-blur-sm"
    >
      <div className="border-foreground/30 bg-card/80 flex flex-col items-center gap-3 rounded-3xl border-2 border-dashed px-10 py-12 text-center shadow-lg">
        <span className="bg-muted text-foreground flex h-14 w-14 animate-bounce items-center justify-center rounded-full">
          <Upload className="h-6 w-6" />
        </span>
        <p className="text-foreground text-base font-medium">{t("dropFilesAttach")}</p>
        <p className="text-muted-foreground text-xs">{t("dropMaxSize", { max: maxSizeMb })}</p>
      </div>
    </div>,
    document.body,
  );
}
