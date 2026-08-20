"use client";

import { createPortal } from "react-dom";
import { Upload } from "lucide-react";

interface FileDropOverlayProps {
  /** Something is being dragged over the page right now. */
  active: boolean;
  /** What dropping will do, in the caller's own words. */
  title: string;
  /** The condition attached to it - a size limit, which formats are taken. */
  hint: string;
}

/**
 * The whole page as a drop target, for as long as a file is over it.
 *
 * Drawn across the viewport rather than around whatever accepts the file,
 * because the point is that there is nothing to aim at: in the chat the target
 * used to be a strip a few centimetres tall, and everywhere else was a
 * navigation away from the conversation.
 *
 * The copy is the caller's - the chat attaches a file to a message, `/context`
 * makes a file out of it, and the sentence has to say which. Everything else is
 * shared, which is why this is here rather than one of these per page.
 *
 * Portalled to the body rather than positioned from here. `fixed` is measured
 * against the nearest ancestor with a transform or a filter rather than against
 * the viewport, and this renders from inside a composer or a page body - one
 * `backdrop-blur` on a wrapper anywhere above it would silently shrink the
 * overlay back to a corner of the screen.
 *
 * Hidden from assistive technology, and that is not an oversight: a drag is a
 * pointer gesture nobody can perform from a keyboard, so this can only ever be
 * noise to a screen reader. The button that does the same thing is the
 * accessible route to it.
 */
export function FileDropOverlay({ active, title, hint }: FileDropOverlayProps) {
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
        <p className="text-foreground text-base font-medium">{title}</p>
        <p className="text-muted-foreground text-xs">{hint}</p>
      </div>
    </div>,
    document.body,
  );
}
