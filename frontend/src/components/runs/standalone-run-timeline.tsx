"use client";

import { MessagesSquare } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { EmptyState, ErrorState } from "@/components/states";
import { Skeleton } from "@/components/ui/skeleton";
import { useRunManifest } from "@/hooks";
import { ApiError } from "@/lib/api-client";

/** Background checks have no chat thread. Their own recorded exchange is the timeline. */
export function StandaloneRunTimeline({ runId }: { runId: string }) {
  const t = useTranslations("pages.runs");
  const ts = useTranslations("states");
  const { manifest, isLoading, error } = useRunManifest(runId);
  if (isLoading) {
    return (
      <div role="status" aria-label={ts("loading")} className="space-y-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }
  if (error && !(error instanceof ApiError && error.status === 404)) {
    return <ErrorState title={t("transcriptCouldNotBeRead")} />;
  }
  if (!manifest?.transcript?.length) {
    return (
      <EmptyState
        icon={MessagesSquare}
        title={t("noTranscriptRecorded")}
        description={
          manifest?.truncated ? t("recordWasTrimmed") : t("thisRunRanWithNoConversation")
        }
      />
    );
  }
  return (
    <div className="space-y-4">
      {manifest.truncated && (
        <p className="text-muted-foreground text-xs">{t("recordWasTrimmed")}</p>
      )}
      <ol className="space-y-4">
        {manifest.transcript.map((message, index) => {
          const text = JSON.stringify(message, null, 2);
          return (
            <li key={index} className="border-border space-y-2 border-l-2 pl-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-muted-foreground text-xs">
                  {t(message.kind === "response" ? "standaloneResponse" : "standaloneRequest")}
                </span>
                <CopyButton text={text} />
              </div>
              <pre className="bg-muted/40 max-h-96 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
                {text}
              </pre>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
