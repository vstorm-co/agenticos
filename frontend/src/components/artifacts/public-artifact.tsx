"use client";

import { useFormatter, useTranslations } from "next-intl";

import { ArtifactFrameView } from "@/components/artifacts/artifact-frame";
import type { PublicArtifact as PublicArtifactData } from "@/types/artifact";

/**
 * What a stranger holding the link sees: the page, its title, and when it was
 * last published. Nothing about who made it or which organization it is from.
 */
export function PublicArtifact({ artifact }: { artifact: PublicArtifactData }) {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  return (
    <main className="bg-background flex min-h-dvh flex-col gap-3 p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-foreground text-lg font-semibold">{artifact.title}</h1>
        <p className="text-muted-foreground text-xs">
          {t("publicUpdated", {
            when: format.dateTime(new Date(artifact.published_at), {
              dateStyle: "medium",
              timeStyle: "short",
            }),
          })}
        </p>
      </header>
      <div className="flex min-h-0 flex-1 flex-col">
        <ArtifactFrameView url={artifact.view.url} title={artifact.title} />
      </div>
    </main>
  );
}
