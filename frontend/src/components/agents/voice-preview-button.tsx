"use client";

import { Play, Square } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button, Spinner } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { Locale } from "@/lib/locales";
import { previewVoice } from "@/lib/voice-api";
import type { VoiceSpec } from "@/types/agents";

type Phase = "idle" | "loading" | "playing";

/**
 * ▶ beside the voice picker: the draft's voice saying one sentence (#54).
 *
 * The sentence is in the section's language where one is set, the console's
 * otherwise. Each voice is fetched once per page - the server caches it too,
 * since every uncached preview is a short paid session on the agent's key.
 * Offered once a provider, a model and a key are chosen; a press while it plays
 * stops it.
 */
export function VoicePreviewButton({ agentId, block }: { agentId: string; block: VoiceSpec }) {
  const t = useTranslations("agents");
  const tErrors = useTranslations("errors");
  // The console's languages are the ones the sentence is written in.
  const locale = useLocale() as Locale;
  const [phase, setPhase] = useState<Phase>("idle");
  const audio = useRef<HTMLAudioElement | null>(null);
  const heard = useRef(new Map<string, string>());

  useEffect(() => {
    const urls = heard.current;
    return () => {
      audio.current?.pause();
      for (const url of urls.values()) URL.revokeObjectURL(url);
    };
  }, []);

  const ready = block.provider !== null && block.secret_id !== null;
  const key = JSON.stringify([
    block.provider,
    block.model,
    block.deployment,
    block.base_model,
    block.secret_id,
    block.voice,
    block.language,
    locale,
  ]);

  const stop = () => {
    audio.current?.pause();
    audio.current = null;
    setPhase("idle");
  };

  const play = async () => {
    setPhase("loading");
    try {
      let url = heard.current.get(key);
      if (url === undefined) {
        url = URL.createObjectURL(await previewVoice(agentId, block, locale));
        heard.current.set(key, url);
      }
      const player = new Audio(url);
      player.onended = stop;
      audio.current = player;
      await player.play();
      setPhase("playing");
    } catch (error) {
      setPhase("idle");
      toast.error(getErrorMessage(error, tErrors));
    }
  };

  const label = phase === "playing" ? t("voicePreviewStop") : t("voicePreview");
  return (
    <Button
      type="button"
      variant="outline"
      size="icon"
      className="h-9 w-9 shrink-0"
      disabled={!ready || phase === "loading"}
      aria-label={label}
      title={ready ? label : t("voicePreviewNeedsKey")}
      onClick={phase === "playing" ? stop : () => void play()}
    >
      {phase === "loading" ? (
        <Spinner className="h-4 w-4" />
      ) : phase === "playing" ? (
        <Square className="h-3.5 w-3.5" />
      ) : (
        <Play className="h-4 w-4" />
      )}
    </Button>
  );
}
