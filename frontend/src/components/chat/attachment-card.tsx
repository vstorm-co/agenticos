"use client";

import { useTranslations } from "next-intl";

import { FileCard, PendingFileCard } from "@/components/files";
import { getFileUrl, type FileUploadResponse } from "@/lib/file-api";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";

/**
 * One thing attached to the message being written.
 *
 * The card itself is `FileCard`, which every surface showing a file without opening
 * it now uses - the transcript and the Files panel had their own, so one file looked
 * like three things on one screen. What is left here is what only the composer
 * knows: that a long paste is labelled as the paste it was rather than by the
 * filename invented for it, and that an image can be addressed for a thumbnail.
 */

interface AttachmentCardProps {
  file: FileUploadResponse;
  /** A long paste, turned into a file. */
  pasted?: boolean;
  onRemove: () => void;
}

export function AttachmentCard({ file, pasted, onRemove }: AttachmentCardProps) {
  const t = useTranslations("chat.input");
  const isImage = resolveFileKind(file.filename, file.mime_type) === "image";

  return (
    <FileCard
      name={file.filename}
      mimeType={file.mime_type}
      size={file.size}
      preview={file.preview}
      imageUrl={isImage ? getFileUrl(file.id) : null}
      typeLabel={
        pasted
          ? t("pastedLabel")
          : suffixOf(file.filename).toUpperCase() || file.file_type.toUpperCase()
      }
      // A chip, because a file here is pending rather than being read: the
      // preview band belongs in the transcript, where a file is content (#927).
      compact
      onRemove={onRemove}
      removeLabel={t("removeAttachment", { name: file.filename })}
    />
  );
}

export function PendingAttachmentCard({ name, size }: { name: string; size: number }) {
  return <PendingFileCard name={name} size={size} compact />;
}
