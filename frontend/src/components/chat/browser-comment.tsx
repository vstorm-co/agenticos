"use client";

import { useState, type MouseEvent } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";

/** A comment on one spot of the page, ready for the composer. */
export interface PageComment {
  /** The page as it was, with the spot ringed. */
  file: File;
  /** The comment, with the address it is about. */
  text: string;
}

/** Where on the picture, as fractions of its width and height. */
interface Spot {
  x: number;
  y: number;
}

/** The ring's radius, as a fraction of the picture's width. */
const RING = 0.025;

/**
 * The picture with `spot` ringed, as a JPEG file.
 *
 * Drawn on a canvas from the frame's own `data:` URL, so the model reads the
 * page as the person saw it when they pointed - the browse may have moved on, or
 * finished and closed its tab, by the time the message is sent.
 */
export async function ringedPicture(image: string, spot: Spot): Promise<File> {
  const picture = new Image();
  picture.src = image;
  await picture.decode();
  const canvas = document.createElement("canvas");
  canvas.width = picture.naturalWidth;
  canvas.height = picture.naturalHeight;
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("no 2d canvas");
  context.drawImage(picture, 0, 0);
  const radius = Math.max(12, canvas.width * RING);
  context.lineWidth = Math.max(3, radius / 5);
  context.strokeStyle = "#e11d48";
  context.beginPath();
  context.arc(spot.x * canvas.width, spot.y * canvas.height, radius, 0, Math.PI * 2);
  context.stroke();
  // JPEG, like the frame it is drawn from: a PNG of a full-density page ran
  // past half a megabyte for one ring.
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", 0.9),
  );
  if (blob === null) throw new Error("the canvas gave no picture");
  return new File([blob], "browser-comment.jpg", { type: "image/jpeg" });
}

/**
 * Point at the page and say something about it.
 *
 * Laid over the live view while commenting: a click marks the spot, a short note
 * goes with it, and both go to the composer - the picture with the spot ringed,
 * the note with the address - for the person to send or keep writing. The way to
 * say "this button, not that one" without describing where it is.
 */
export function BrowserCommentLayer({
  image,
  url,
  onComment,
  onDone,
}: {
  image: string;
  url: string | null;
  onComment: (comment: PageComment) => void;
  onDone: () => void;
}) {
  const t = useTranslations("chat");
  const [spot, setSpot] = useState<Spot | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const mark = (event: MouseEvent<HTMLDivElement>) => {
    if (spot !== null) return;
    const box = event.currentTarget.getBoundingClientRect();
    setSpot({
      x: (event.clientX - box.left) / box.width,
      y: (event.clientY - box.top) / box.height,
    });
  };

  const send = async () => {
    if (spot === null || !note.trim()) return;
    setBusy(true);
    try {
      const file = await ringedPicture(image, spot);
      const text = url ? t("browserCommentMessage", { url, note: note.trim() }) : note.trim();
      onComment({ file, text });
      onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    // A click target over the picture, not a control of its own: the form that
    // opens is what a keyboard reaches.
    <div
      className="absolute inset-0 z-10 cursor-crosshair bg-sky-500/[0.04]"
      onClick={mark}
      data-testid="browser-comment-layer"
    >
      {spot === null ? (
        <span className="bg-foreground text-background pointer-events-none absolute top-3 left-1/2 -translate-x-1/2 rounded-full px-3 py-1.5 text-xs font-medium shadow-lg">
          {t("browserCommentPick")}
        </span>
      ) : (
        <>
          <span
            aria-hidden
            className="pointer-events-none absolute size-6 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-rose-600 shadow"
            style={{ left: `${spot.x * 100}%`, top: `${spot.y * 100}%` }}
          />
          <form
            role="dialog"
            aria-label={t("browserComment")}
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
            onClick={(event) => event.stopPropagation()}
            className="bg-background border-border absolute w-64 max-w-[calc(100%-1rem)] space-y-2 rounded-xl border p-2.5 shadow-xl"
            style={{
              // i18n-exempt: a CSS length, not copy.
              left: `clamp(0.5rem, calc(${spot.x * 100}% - 8rem), calc(100% - 16.5rem))`,
              top: spot.y > 0.6 ? undefined : `calc(${spot.y * 100}% + 1.25rem)`,
              bottom: spot.y > 0.6 ? `calc(${(1 - spot.y) * 100}% + 1.25rem)` : undefined,
            }}
          >
            <textarea
              autoFocus
              value={note}
              onChange={(event) => setNote(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
                if (event.key === "Escape") {
                  event.stopPropagation();
                  onDone();
                }
              }}
              placeholder={t("browserCommentPlaceholder")}
              aria-label={t("browserCommentPlaceholder")}
              rows={2}
              className="bg-muted/60 placeholder:text-muted-foreground w-full resize-none rounded-lg px-2.5 py-2 text-sm outline-none"
            />
            <div className="flex justify-end gap-1.5">
              <Button type="button" size="sm" variant="ghost" onClick={onDone}>
                {t("browserCommentCancel")}
              </Button>
              <Button type="submit" size="sm" disabled={busy || !note.trim()}>
                {t("browserCommentAdd")}
              </Button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
