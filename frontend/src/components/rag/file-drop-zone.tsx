"use client";

import { useRef, useState, type ReactNode } from "react";
import { Upload } from "lucide-react";
import { useTranslations } from "next-intl";

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
}: {
  /** Named in the overlay, so a drop says which collection it will land in. */
  collectionName: string;
  onFiles: (files: FileList) => void;
  children: ReactNode;
}) {
  const t = useTranslations("pages.kb");
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);

  return (
    <div
      className="relative pb-8"
      onDragEnter={(e) => {
        if (e.dataTransfer.types.includes(DRAGGED_FILES)) {
          dragCounter.current += 1;
          setIsDragging(true);
        }
      }}
      onDragLeave={() => {
        dragCounter.current = Math.max(0, dragCounter.current - 1);
        if (dragCounter.current === 0) setIsDragging(false);
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes(DRAGGED_FILES)) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        dragCounter.current = 0;
        setIsDragging(false);
        onFiles(e.dataTransfer.files);
      }}
    >
      {isDragging && (
        <div className="bg-background/80 fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm">
          <div className="border-foreground/30 bg-card flex flex-col items-center gap-4 rounded-xl border-2 border-dashed px-12 py-16">
            <span className="bg-muted text-foreground inline-flex h-14 w-14 items-center justify-center rounded-xl">
              <Upload className="h-6 w-6" />
            </span>
            <div className="text-center">
              <p className="text-foreground text-lg font-semibold">{t("dropUpload")}</p>
              <p className="text-muted-foreground mt-1 text-sm">
                {t.rich("filesWillBeAddedTo", {
                  name: collectionName,
                  strong: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
                })}
              </p>
            </div>
          </div>
        </div>
      )}
      {children}
    </div>
  );
}
