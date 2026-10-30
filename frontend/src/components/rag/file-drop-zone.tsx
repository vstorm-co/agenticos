"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

/**
 * The `DataTransfer` type a dragged file carries, spelled as the DOM spells it.
 *
 * A machine value, not copy - and it was in `messages/en.json` as `files2` and
 * `files3`, where a translator opening `pl.json` would have been asked to
 * translate it. "Pliki" is never in `dataTransfer.types`, so the whole
 * drag-and-drop path would have gone quiet under `pl` with nothing on screen
 * explaining it.
 */
const DRAGGED_FILES = "Files";

/**
 * Whether a drag may be carrying files.
 *
 * Firefox hands some drag events over with no `dataTransfer` at all. Reading
 * `.types` off it threw, `dragover` then never called `preventDefault`, and the
 * browser refused the drop - so nothing uploaded. Such a drag is treated as one
 * that may carry files; the drop itself decides, by whether any arrived.
 */
function mayCarryFiles(transfer: DataTransfer | null): boolean {
  return transfer === null || transfer.types.includes(DRAGGED_FILES);
}

/**
 * Wraps a page so that a file dropped anywhere on it is an upload.
 *
 * The whole page rather than a bordered rectangle, because the target somebody
 * aims at is the list of documents they can see. Nothing here is state the page
 * needs: the counter exists only because `dragleave` fires for every child the
 * pointer crosses, so a single boolean flickers the overlay off mid-drag.
 */
export function FileDropZone({
  collectionName,
  onFiles,
  children,
  className,
}: {
  /** Named in the overlay, so a drop says which collection it will land in. */
  collectionName: string;
  onFiles: (files: FileList) => void;
  children: ReactNode;
  /** Replaces the default bottom padding: a pane that fills the page lays itself out. */
  className?: string;
}) {
  const t = useTranslations("pages.kb");
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);
  const reset = () => {
    dragCounter.current = 0;
    setIsDragging(false);
  };
  useEffect(() => {
    const clear = () => {
      dragCounter.current = 0;
      setIsDragging(false);
    };
    const dropped = (event: DragEvent) => {
      // A missed drop must not replace the console with the dragged file.
      if (event.dataTransfer?.types.includes(DRAGGED_FILES)) event.preventDefault();
      clear();
    };
    window.addEventListener("dragend", clear);
    window.addEventListener("drop", dropped);
    window.addEventListener("blur", clear);
    return () => {
      window.removeEventListener("dragend", clear);
      window.removeEventListener("drop", dropped);
      window.removeEventListener("blur", clear);
    };
  }, []);

  return (
    <div
      className={cn("relative", className ?? "pb-8")}
      onDragEnter={(e) => {
        if (mayCarryFiles(e.dataTransfer)) {
          dragCounter.current += 1;
          setIsDragging(true);
        }
      }}
      onDragLeave={(event) => {
        dragCounter.current = Math.max(0, dragCounter.current - 1);
        if (event.relatedTarget instanceof Node) {
          if (event.currentTarget.contains(event.relatedTarget)) return;
          reset();
        } else {
          // WebKit can omit relatedTarget while crossing a child boundary.
          const rect = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX >= rect.left &&
            event.clientX < rect.right &&
            event.clientY >= rect.top &&
            event.clientY < rect.bottom
          )
            return;
          if (dragCounter.current === 0) setIsDragging(false);
        }
      }}
      onDragOver={(e) => {
        if (mayCarryFiles(e.dataTransfer)) {
          e.preventDefault();
          if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        }
      }}
      onDropCapture={reset}
      onDrop={(e) => {
        if (!mayCarryFiles(e.dataTransfer)) return;
        e.preventDefault();
        const files = e.dataTransfer?.files;
        if (files && files.length > 0) onFiles(files);
      }}
    >
      {isDragging && (
        <div
          aria-hidden="true"
          data-testid="project-file-drop-overlay"
          className="border-foreground/30 bg-foreground/[0.025] pointer-events-none absolute inset-0 z-20 rounded-xl border-2 border-dashed"
        >
          <div className="bg-popover text-foreground animate-in fade-in-0 absolute bottom-3 left-3 flex max-w-[calc(100%-1.5rem)] items-center gap-2 rounded-lg border px-3 py-2 shadow-sm">
            <Upload className="size-4 shrink-0" />
            <span className="min-w-0 truncate text-xs font-medium">
              {t("dropUpload")} · {collectionName}
            </span>
          </div>
        </div>
      )}
      {children}
    </div>
  );
}
