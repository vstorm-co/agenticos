"use client";

import Image from "next/image";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

import { FileIcon } from "./file-icon";
import { Spinner } from "@/components/ui";
import { resolveFileKind, suffixOf } from "@/lib/file-kinds";
import { cn, formatBytes } from "@/lib/utils";

/**
 * One file, as a card - wherever a file is shown without being opened.
 *
 * There were three of these and a file looked like three different things on one
 * screen: a horizontal pill with a generic document glyph in the transcript, a
 * vertical tile with a truncated name in the Files panel, and the composer's card
 * with an excerpt and a size. Same file, three answers, which is #136's problem one
 * layer out - that change unified what *opening* a file means and left what showing
 * one means alone.
 *
 * The shape is the composer's, because it was the only one that answered the
 * question somebody actually has: **what is in this, and is it the right one.** So:
 * the name unabridged, then the content if there is any to show - a thumbnail for an
 * image, the first lines for anything textual - then what it is and how big.
 *
 * Nothing here fetches. A preview is passed in or it is not: the composer has an
 * excerpt from the upload response, the transcript has none, and a card that went
 * looking would issue a request per file in a listing.
 */

interface FileCardProps {
  /** Shown in full, wrapped rather than truncated: a name is how somebody checks. */
  name: string;
  /** What the origin says it is, where it knows. A name is only a suggestion. */
  mimeType?: string | null;
  size?: number | null;
  /** The first lines of it, for anything textual. Absent is normal, not a failure. */
  preview?: string | null;
  /** A thumbnail for an image, where the surface can address the bytes. */
  imageUrl?: string | null;
  /**
   * What to call the type, when the suffix is not the answer.
   *
   * The paste in the composer is the case: labelled as the paste it was rather than
   * by the filename invented for it, which nobody chose and nobody recognises.
   */
  typeLabel?: string;
  onOpen?: () => void;
  onRemove?: () => void;
  /** Removing it, in the words of whichever surface holds it. */
  removeLabel?: string;
  className?: string;
}

const CARD = "border-border bg-card relative flex w-56 flex-col gap-1.5 rounded-lg border p-2";

export function FileCard({
  name,
  mimeType,
  size,
  preview,
  imageUrl,
  typeLabel,
  onOpen,
  onRemove,
  removeLabel,
  className,
}: FileCardProps) {
  const t = useTranslations("files");
  const isImage = resolveFileKind(name, mimeType) === "image";
  const label = typeLabel ?? suffixOf(name).toUpperCase() ?? "";
  const meta = [label, size == null ? null : formatBytes(size)].filter(Boolean).join(" · ");

  const body = (
    <>
      <div className="flex items-start gap-1.5">
        <FileIcon
          name={name}
          mimeType={mimeType}
          className="text-muted-foreground mt-px h-3.5 w-3.5 shrink-0"
        />
        {/* `min-w-0` is what makes the wrap happen: a flex child's default minimum is
            its content, so without it a long unbroken name refuses to shrink and
            runs out past the card's border rather than wrapping inside it.
            `break-all` because a filename has no spaces to break at -
            `Hiszpanski_od_zera_do_B1.xlsx` is one word to the browser. */}
        <span className="min-w-0 flex-1 text-xs leading-snug font-medium break-all">{name}</span>
      </div>

      {/* The middle band is the point of the card, and it is *reserved* whether or
          not there is anything to put in it: cards of two heights in one strip read
          as two kinds of thing. A file with no preview shows its mark instead. */}
      <div className="flex h-16 w-full items-center justify-center overflow-hidden rounded">
        {isImage && imageUrl != null ? (
          <div className="bg-muted relative h-full w-full">
            <Image src={imageUrl} alt={name} fill className="object-cover" unoptimized />
          </div>
        ) : preview ? (
          <p className="text-muted-foreground line-clamp-4 w-full self-start font-mono text-[10px] leading-tight whitespace-pre-wrap">
            {preview}
          </p>
        ) : (
          <FileIcon name={name} mimeType={mimeType} className="text-muted-foreground/40 h-8 w-8" />
        )}
      </div>

      {meta !== "" && (
        <p className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
          {meta}
        </p>
      )}
    </>
  );

  return (
    <div className={cn(CARD, onRemove !== undefined && "pr-7", className)}>
      {onOpen !== undefined ? (
        <button
          type="button"
          onClick={onOpen}
          title={t("openFile", { name })}
          className="hover:border-foreground/30 -m-2 flex flex-col gap-1.5 rounded-lg border border-transparent p-2 text-left transition-colors"
        >
          {body}
        </button>
      ) : (
        body
      )}

      {onRemove !== undefined && (
        // Always rendered, never on hover: a hover-only control is unreachable on a
        // touch screen and invisible to anybody who does not think to try.
        <button
          type="button"
          onClick={onRemove}
          aria-label={removeLabel ?? t("removeFile", { name })}
          className="hover:bg-muted text-muted-foreground hover:text-foreground absolute top-1.5 right-1.5 rounded p-0.5"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

/**
 * A file on its way to the server, in the place it will occupy once it arrives.
 *
 * In place rather than beside: the dashed box this replaces sat *after* every
 * finished card, so uploading a second file made the first one appear to move.
 */
export function PendingFileCard({ name, size }: { name: string; size: number }) {
  const t = useTranslations("files");

  return (
    <div className={CARD}>
      <div className="flex items-start gap-1.5">
        <Spinner className="text-muted-foreground mt-px h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1 text-xs leading-snug font-medium break-all">{name}</span>
      </div>
      <div className="h-16 w-full" />
      <p className="text-muted-foreground font-mono text-[10px] tracking-wider uppercase">
        {t("uploading", { size: formatBytes(size) })}
      </p>
    </div>
  );
}
