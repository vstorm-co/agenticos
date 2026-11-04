"use client";
import { Monitor } from "lucide-react";
import { useTranslations } from "next-intl";

export interface DesktopScreenshotPayload {
  /** What the agent said the screenshot shows, shown under it and as its alt text. */
  caption: string;
  /**
   * Where the browser fetches it, through the same-origin proxy that forwards the
   * session - `/api/generated/{filename}`. Null when the run had no organization
   * to store it for, in which case there is nothing to show.
   */
  url: string | null;
}

/** Parse a `computer_save_screenshot` result, or null if it isn't one
 *  (an error sentence or another tool's result → the default renderer). */
export function parseDesktopScreenshot(result: string): DesktopScreenshotPayload | null {
  try {
    const p = JSON.parse(result);
    if (p && typeof p === "object" && p.kind === "desktop_screenshot") {
      return {
        caption: typeof p.caption === "string" ? p.caption : "",
        url: typeof p.filename === "string" ? `/api/generated/${p.filename}` : null,
      };
    }
  } catch {
    /* not JSON - fall back to the raw renderer */
  }
  return null;
}

/** A screenshot the agent kept: the desktop as it was, opening at full size. */
export function DesktopScreenshotResult({ data }: { data: DesktopScreenshotPayload }) {
  const t = useTranslations("chat.tools");
  if (data.url === null) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-2 text-sm">
        <Monitor className="h-4 w-4" aria-hidden />
        {t("screenshotNotStored")}
      </div>
    );
  }

  return (
    <figure className="py-1">
      {/* Linked to itself: the chat shows it scaled down, and a screenshot kept as
          evidence is read at the size it was taken. */}
      <a href={data.url} target="_blank" rel="noopener noreferrer">
        {/* A plain <img>, not next/image, for the reason the generated image is. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={data.url}
          alt={data.caption}
          className="border-foreground/10 max-h-[28rem] w-auto rounded-xl border"
        />
      </a>
      {data.caption && (
        <figcaption className="text-muted-foreground mt-1 text-xs leading-relaxed">
          {data.caption}
        </figcaption>
      )}
    </figure>
  );
}
