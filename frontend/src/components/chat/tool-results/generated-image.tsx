"use client";
import { ImageIcon } from "lucide-react";
import { useTranslations } from "next-intl";

export interface GeneratedImagePayload {
  /** The prompt the image was drawn from, shown as a caption and alt text. */
  prompt: string;
  /**
   * Where the browser fetches the image, through the same-origin proxy that
   * forwards the session - `/api/generated/{filename}`. Null when the image was
   * generated but not stored (a run with no organization to scope it to), in
   * which case there is nothing to show.
   */
  url: string | null;
}

/** Parse a structured `generate_image` result, or null if it isn't one
 *  (an error string / other tool → caller falls back to the default renderer). */
export function parseGeneratedImage(result: string): GeneratedImagePayload | null {
  try {
    const p = JSON.parse(result);
    if (p && typeof p === "object" && p.kind === "generated_image") {
      const filename = typeof p.filename === "string" ? p.filename : null;
      return {
        prompt: String(p.prompt ?? ""),
        url: filename === null ? null : `/api/generated/${filename}`,
      };
    }
  } catch {
    /* not JSON - fall back to the raw renderer */
  }
  return null;
}

export function GeneratedImageResult({ data }: { data: GeneratedImagePayload }) {
  const t = useTranslations("chat.tools");
  if (data.url === null) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-2 text-sm">
        <ImageIcon className="h-4 w-4" />
        {t("imageNotStored")}
      </div>
    );
  }

  return (
    <figure className="py-1">
      {/* A plain <img>, not next/image: the src is a same-origin proxy route,
          which next/image would want declared in next.config remote patterns. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={data.url}
        alt={data.prompt}
        className="border-foreground/10 max-h-[28rem] w-auto rounded-xl border"
      />
      {data.prompt && (
        <figcaption className="text-foreground/55 mt-1 text-[11px] leading-relaxed">
          {data.prompt}
        </figcaption>
      )}
    </figure>
  );
}
