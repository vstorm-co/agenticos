"use client";
import { AudioLines } from "lucide-react";
import { useTranslations } from "next-intl";

import { generatedMediaUrl, SESSION_SURFACE, type MediaSurface } from "@/lib/generated-media";

export interface GeneratedSpeechPayload {
  /** The voice that spoke, shown under the player. */
  voice: string;
  /**
   * Where the browser fetches the clip, on the surface it is shown on - see
   * `generatedMediaUrl`. Null when the clip was made but not stored (a run with no
   * organization to scope it to), in which case there is nothing to play.
   */
  url: string | null;
}

/** Parse a structured `generate_speech` result, or null if it isn't one
 *  (an error string / other tool → caller falls back to the default renderer). */
export function parseGeneratedSpeech(
  result: string,
  surface: MediaSurface = SESSION_SURFACE,
): GeneratedSpeechPayload | null {
  try {
    const p = JSON.parse(result);
    if (p && typeof p === "object" && p.kind === "generated_speech") {
      return {
        voice: String(p.voice ?? ""),
        url: generatedMediaUrl(p, surface),
      };
    }
  } catch {
    /* not JSON - fall back to the raw renderer */
  }
  return null;
}

/** A clip of generated speech, played where a generated image would be shown. */
export function GeneratedSpeechResult({ data }: { data: GeneratedSpeechPayload }) {
  const t = useTranslations("chat.tools");
  if (data.url === null) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 py-2 text-sm">
        <AudioLines className="h-4 w-4" />
        {t("speechNotStored")}
      </div>
    );
  }

  return (
    <figure className="py-1">
      <audio src={data.url} controls preload="metadata" className="w-full max-w-md" />
      {data.voice && (
        <figcaption className="text-muted-foreground mt-1 text-xs leading-relaxed">
          {t("spokenBy", { voice: data.voice })}
        </figcaption>
      )}
    </figure>
  );
}
