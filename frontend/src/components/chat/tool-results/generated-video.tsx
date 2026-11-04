"use client";
import { Clapperboard } from "lucide-react";
import { useTranslations } from "next-intl";

import { generatedMediaUrl, SESSION_SURFACE, type MediaSurface } from "@/lib/generated-media";

export interface GeneratedVideoPayload {
  /** What the clip shows, as the agent described it - the caption. */
  prompt: string;
  /**
   * Where the browser fetches the clip, on the surface it is shown on - see
   * `generatedMediaUrl`. Null when the clip was made but not stored (a run with no
   * organization to scope it to), in which case there is nothing to play.
   */
  url: string | null;
}

/** Parse a structured `generate_video` result, or null if it isn't one
 *  (an error string / other tool → caller falls back to the default renderer). */
export function parseGeneratedVideo(
  result: string,
  surface: MediaSurface = SESSION_SURFACE,
): GeneratedVideoPayload | null {
  try {
    const p = JSON.parse(result);
    if (p && typeof p === "object" && p.kind === "generated_video") {
      return {
        prompt: String(p.prompt ?? ""),
        url: generatedMediaUrl(p, surface),
      };
    }
  } catch {
    /* not JSON - fall back to the raw renderer */
  }
  return null;
}

/** A generated clip, played where a generated image would be shown. */
export function GeneratedVideoResult({ data }: { data: GeneratedVideoPayload }) {
  const t = useTranslations("chat.tools");
  if (data.url === null) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-2 text-sm">
        <Clapperboard className="h-4 w-4" />
        {t("videoNotStored")}
      </div>
    );
  }

  return (
    <figure className="py-1">
      <video
        src={data.url}
        controls
        preload="metadata"
        className="border-foreground/10 max-h-[28rem] w-auto rounded-xl border bg-black"
      />
      {data.prompt && (
        <figcaption className="text-muted-foreground mt-1 text-xs leading-relaxed">
          {data.prompt}
        </figcaption>
      )}
    </figure>
  );
}
