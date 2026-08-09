"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** The DOM's own name for "this drag carries files" - a constant, not copy. */
const FILES = "Files"; /* i18n-exempt: a DataTransfer type name, defined by the DOM */

interface FileDropOptions {
  /** What to do with the files somebody dropped. */
  onFiles: (files: File[]) => void;
  /** Do not accept anything, and draw nothing. */
  disabled?: boolean;
}

/**
 * Files dropped anywhere on the page, not only on the thing that accepts them.
 *
 * The composer was the only drop target, which made attaching a file a game of
 * hitting a strip a few centimetres tall - and a miss was not a no-op: the
 * browser's default for a dropped file is to *open* it, so the tab navigated
 * away from the conversation and whatever was half-typed in it. Listening on the
 * window fixes both halves at once, because the same `preventDefault` that lets
 * us take the file is what stops the browser taking it.
 *
 * `dragenter` and `dragleave` fire for every element the pointer crosses, so a
 * drag over a transcript full of cards is a stream of both. The depth counter is
 * what makes the overlay stay put instead of flickering once per child; `drop`
 * and `dragend` reset it outright, because a drag that ends never balances its
 * last `dragenter`.
 *
 * Only file drags count. Dragging selected text, a link, or one of the app's own
 * draggable rows must behave as it always did, so anything without `Files` in
 * its `dataTransfer` is left entirely alone - not even prevented.
 */
export function useFileDrop({ onFiles, disabled = false }: FileDropOptions): {
  isDragging: boolean;
} {
  const [isDragging, setIsDragging] = useState(false);
  const depth = useRef(0);

  // Read through a ref inside the listeners so the effect does not re-subscribe
  // on every render of the caller - `onFiles` is rebuilt whenever its own
  // dependencies change, and re-binding four window listeners mid-drag drops the
  // drag.
  const handler = useRef(onFiles);
  useEffect(() => {
    handler.current = onFiles;
  }, [onFiles]);

  const stop = useCallback(() => {
    depth.current = 0;
    setIsDragging(false);
  }, []);

  useEffect(() => {
    if (disabled) return;

    // A predicate rather than a boolean, so the handlers below read `files` off a
    // transfer this has already proved is there - the alternative is a `?.` on
    // every use, which is a fallback for a case the guard has excluded.
    const carriesFiles = (event: DragEvent): event is DragEvent & { dataTransfer: DataTransfer } =>
      event.dataTransfer !== null && Array.from(event.dataTransfer.types).includes(FILES);

    const onEnter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setIsDragging(true);
    };
    const onOver = (event: DragEvent) => {
      // Required on every `dragover`, not just on enter: without it the drop is
      // never delivered and the browser opens the file instead.
      if (carriesFiles(event)) event.preventDefault();
    };
    const onLeave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth.current -= 1;
      if (depth.current <= 0) stop();
    };
    const onDrop = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      stop();
      const files = Array.from(event.dataTransfer.files);
      if (files.length > 0) handler.current(files);
    };

    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    // A drag cancelled with Escape, or dropped outside the window, ends here and
    // nowhere else - without it the overlay stays up over a page nobody is
    // dragging anything onto.
    window.addEventListener("dragend", stop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
      window.removeEventListener("dragend", stop);
      // The listeners are gone, so nothing will ever take the overlay down.
      stop();
    };
  }, [disabled, stop]);

  return { isDragging };
}
