"use client";

import { MessagesSquare } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { EmptyState, ErrorState } from "@/components/states";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
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
  const transcript = manifest.transcript;
  return (
    <div className="space-y-4">
      {manifest.truncated && (
        <p className="text-muted-foreground text-xs">{t("recordWasTrimmed")}</p>
      )}
      <ol className="divide-border divide-y">
        {transcript.map((message, index) => {
          const text = JSON.stringify(message, null, 2);
          const parts = Array.isArray(message.parts) ? message.parts : [];
          const readable = parts.flatMap((part: unknown): string[] => {
            if (typeof part !== "object" || part === null || !("content" in part)) return [];
            return typeof part.content === "string" && part.content.trim() ? [part.content] : [];
          });
          const label = t(message.kind === "response" ? "standaloneResponse" : "standaloneRequest");
          return (
            <li key={index}>
              <NativeDisclosure open={index === transcript.length - 1} className="py-3">
                <summary className="cursor-pointer text-sm select-none">
                  <span className="text-muted-foreground mr-2 font-mono text-xs">
                    {t("requestIndex", { index: index + 1 })}
                  </span>
                  <span className="font-medium">{label}</span>
                  {readable[0] && (
                    <span className="text-muted-foreground mt-1 block truncate pl-6 text-xs">
                      {readable[0]}
                    </span>
                  )}
                </summary>
                <div className="space-y-3 pt-3 pl-6">
                  {readable.map((content, partIndex) => (
                    <p key={partIndex} className="text-sm break-words whitespace-pre-wrap">
                      {content}
                    </p>
                  ))}
                  <NativeDisclosure open={readable.length === 0}>
                    <summary className="text-muted-foreground cursor-pointer text-xs select-none">
                      {t("rawRecord")}
                    </summary>
                    <div className="flex justify-end">
                      <CopyButton text={text} />
                    </div>
                    <pre
                      // Scrollable raw records must be reachable by keyboard.
                      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
                      tabIndex={0}
                      role="region"
                      aria-label={`${label} · ${t("rawRecord")}`}
                      className="bg-muted/40 max-h-96 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap"
                    >
                      <code>{text}</code>
                    </pre>
                  </NativeDisclosure>
                </div>
              </NativeDisclosure>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
