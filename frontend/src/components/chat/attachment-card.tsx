"use client";

import Image from "next/image";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { FileIcon } from "@/components/files";
import { Spinner } from "@/components/ui";
import { getFileUrl, type FileUploadResponse } from "@/lib/file-api";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";
import { formatBytes } from "@/lib/utils";

/**
 * One thing attached to the message being written.
 *
 * A card rather than the tag this used to be. `_allegro_system_prompt…` in a
 * grey pill truncated at 150px says almost nothing: not what is in the file, not
 * how big it is, and not whether the right one was picked — which is the only
 * question somebody has between attaching and sending. So the card carries the
 * name unabridged, an excerpt of the text, and what it is beside how large.
 *
 * The remove control is always rendered, never on hover. The thumbnail it
 * replaces revealed its × on `group-hover`, which on a touch screen is
 * unreachable and to everybody else is invisible until guessed at.
 *
 * What kind of file it is comes from `resolveFileKind` and the mark from
 * `FileIcon`, the same two the viewer this card opens into uses. A card that read
 * the suffix for itself is how a `.csv` came to be a spreadsheet to the icon and
 * plain text to the viewer on one screen (#136).
 */

const CARD = "border-border bg-card relative flex w-56 flex-col gap-1.5 rounded-lg border p-2 pr-7";

/** How the type reads on the card: the suffix, or the classification if it has none. */
function typeLabel(file: FileUploadResponse): string {
  return (suffixOf(file.filename) || file.file_type).toUpperCase();
}

interface AttachmentCardProps {
  file: FileUploadResponse;
  /**
   * A long paste, turned into a file. Labelled as the paste it was rather than
   * by the filename invented for it, which nobody chose and nobody recognises.
   */
  pasted?: boolean;
  onRemove: () => void;
}

export function AttachmentCard({ file, pasted, onRemove }: AttachmentCardProps) {
  const t = useTranslations("chat.input");
  const isImage = resolveFileKind(file.filename, file.mime_type) === "image";

  return (
    <div className={CARD}>
      <CardHeading>
        <FileIcon
          name={file.filename}
          mimeType={file.mime_type}
          className="text-muted-foreground h-3.5 w-3.5 shrink-0"
        />
        <span className="text-xs leading-snug font-medium break-words">{file.filename}</span>
      </CardHeading>

      {isImage ? (
        <div className="bg-muted relative h-16 w-full overflow-hidden rounded">
          <Image
            src={getFileUrl(file.id)}
            alt={file.filename}
            fill
            className="object-cover"
            unoptimized
          />
        </div>
      ) : (
        file.preview && (
          <p className="text-muted-foreground line-clamp-3 font-mono text-[10px] leading-tight whitespace-pre-wrap">
            {file.preview}
          </p>
        )
      )}

      <CardMeta>
        {t("attachmentMeta", {
          label: pasted ? t("pastedLabel") : typeLabel(file),
          size: formatBytes(file.size),
        })}
      </CardMeta>

      <button
        type="button"
        onClick={onRemove}
        aria-label={t("removeAttachment", { name: file.filename })}
        className="hover:bg-muted text-muted-foreground hover:text-foreground absolute top-1.5 right-1.5 rounded p-0.5"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

/**
 * A file on its way to the server, in the place it will occupy once it arrives.
 *
 * In place rather than beside: the dashed box this replaces sat *after* every
 * finished card, so uploading a second file made the first one appear to move.
 */
export function PendingAttachmentCard({ name, size }: { name: string; size: number }) {
  const t = useTranslations("chat.input");

  return (
    <div className={CARD}>
      <CardHeading>
        <Spinner className="text-muted-foreground h-3.5 w-3.5 shrink-0" />
        <span className="text-xs leading-snug font-medium break-words">{name}</span>
      </CardHeading>
      <CardMeta>{t("attachmentUploading", { size: formatBytes(size) })}</CardMeta>
    </div>
  );
}

function CardHeading({ children }: { children: React.ReactNode }) {
  return <div className="flex items-start gap-1.5">{children}</div>;
}

function CardMeta({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
      {children}
    </p>
  );
}
