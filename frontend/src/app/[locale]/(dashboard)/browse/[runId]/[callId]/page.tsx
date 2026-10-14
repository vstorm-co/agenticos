"use client";

import { use } from "react";
import { MonitorPlay } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrowserWindow } from "@/components/chat/browser-window";
import { EmptyState, LoadingState } from "@/components/states";
import { useLiveBrowse } from "@/hooks/use-live-browse";
import { isRunning } from "@/lib/browse";

interface PageProps {
  params: Promise<{ runId: string; callId: string }>;
}

/**
 * One browse, live, from wherever it was started (#2128).
 *
 * The address a channel posts and the chat links to: the same browser window
 * the chat docks beside a conversation, given the page. The person the run acts
 * for, or someone who may edit the agent, can take it over from its toolbar -
 * taking over waits for the step in flight, then the page is theirs to click,
 * type into and scroll, and handing it back lets the agent carry on from where
 * they left it. What they type is passed to the page and never recorded.
 */
export default function LiveBrowsePage({ params }: PageProps) {
  const { runId, callId } = use(params);
  const t = useTranslations("browse");
  const { browse, task, canControl, canRemember, status, send } = useLiveBrowse(runId, callId);

  if (status === "gone" || status === "forbidden" || status === "unavailable") {
    return (
      <EmptyState icon={MonitorPlay} title={t(`${status}Title`)} description={t(`${status}Body`)} />
    );
  }
  if (status === "connecting" || browse === null) {
    return <LoadingState variant="skeleton-panel" rows={3} />;
  }

  return (
    <div className="mx-auto flex h-[calc(100dvh-7rem)] max-w-6xl flex-col gap-3">
      <div className="min-w-0 space-y-1 px-1">
        <h1 className="text-foreground text-lg font-semibold">{t("title")}</h1>
        <p className="text-foreground/80 line-clamp-2 text-sm leading-relaxed">
          {task || browse.goal}
        </p>
        {isRunning(browse) && !canControl && (
          <p className="text-muted-foreground text-xs">{t("watchOnly")}</p>
        )}
      </div>
      <div className="ring-foreground/10 min-h-0 flex-1 overflow-hidden rounded-2xl ring-1">
        <BrowserWindow waitForFit browse={browse} control={{ canControl, canRemember, send }} />
      </div>
    </div>
  );
}
