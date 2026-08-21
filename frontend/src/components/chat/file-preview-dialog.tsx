"use client";

import { useMemo } from "react";

import { FileViewer } from "@/components/files";
import { useFilePreviewStore } from "@/stores";
import { attachmentAccess } from "@/lib/file-api";

/**
 * The attachment selected in the chat, opened.
 *
 * **A dialog, and it took a screenshot to settle it.** This was a resizable
 * right-hand panel, on the argument that an attachment is read *beside* the
 * message carrying it. What that produced in practice was two panels sharing the
 * right side of the window - the file at 480 pixels next to the list of files -
 * with a 119-page PDF rendered in a column narrower than one of its own lines.
 * The reading-beside argument was real and it lost to arithmetic: there is one
 * right-hand side, the transcript wants the rest, and a file is the thing you
 * opened it to look at.
 *
 * So it is `FileViewer`, the same dialog every other surface opens - which is
 * also the end of the exception #136 left behind, where the panel people hit
 * most often was the one running its own chrome, its own header and its own
 * width.
 *
 * The store carries the whole conversation's files, so the carousel pages through
 * every one of them wherever the reader clicked - a card in the transcript and a
 * tile in the Files panel open the same set, which they did not when each surface
 * passed the files it happened to be holding.
 */
export function FilePreviewDialog() {
  const files = useFilePreviewStore((state) => state.available);
  const openId = useFilePreviewStore((state) => state.openId);
  const select = useFilePreviewStore((state) => state.select);
  const close = useFilePreviewStore((state) => state.close);

  const index = files.findIndex((one) => one.id === openId);
  const file = openId === null || index === -1 ? null : files[index]!;
  // Keyed on the id so a paged-to file starts its own fetch rather than inheriting
  // the previous one's. `useMemo` on the id and not on the object: the store hands
  // out the same array, but a caller re-rendering its list hands out new objects.
  const access = useMemo(() => (file === null ? null : attachmentAccess(file)), [file]);

  if (file === null || access === null) return null;

  return (
    <FileViewer
      key={file.id}
      file={{ name: file.filename, mimeType: file.mime_type }}
      access={access}
      navigation={{ names: files.map((one) => one.filename), index, onSelect: select }}
      onClose={close}
    />
  );
}
