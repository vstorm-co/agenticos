"use client";

import { use } from "react";
import { MonitorPlay } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrowserWindow } from "@/components/chat/browser-window";
import { PageHeader } from "@/components/dashboard/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/states";
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
  const ts = useTranslations("states");
  const { browse, task, canControl, canRemember, status, send } = useLiveBrowse(runId, callId);

  if (status === "gone" || status === "forbidden" || status === "unavailable") {
    return (
      <EmptyState icon={MonitorPlay} title={t(`${status}Title`)} description={t(`${status}Body`)} />
    );
  }
  if (status === "connecting" || browse === null) {
    return (
      <div
        className="mx-auto flex h-[calc(100dvh-7rem)] w-full max-w-7xl min-w-0 flex-col gap-4"
        role="status"
        aria-label={ts("loading")}
        aria-busy
      >
        <PageHeader
          className="mb-0 md:mb-0"
          title={t("title")}
          description={
            <span
              aria-hidden
              className="bg-muted inline-block h-4 w-2/3 animate-pulse rounded-md"
            />
          }
        />
        <Skeleton className="min-h-0 w-full flex-1 rounded-2xl border shadow-sm" />
      </div>
    );
  }

  return (
    // `w-full` is load-bearing: the window asks the browser to lay the page out
    // at its own size, so a wrapper that shrank to its content shrank to the
    // last picture - and a page once opened narrow stayed a phone layout.
    <div className="mx-auto flex h-[calc(100dvh-7rem)] w-full max-w-7xl min-w-0 flex-col gap-4">
      <PageHeader
        className="mb-0 md:mb-0"
        title={t("title")}
        description={
          <>
            <span className="line-clamp-2">{task || browse.goal}</span>
            {isRunning(browse) && !canControl && (
              <span className="mt-1 block text-xs">{t("watchOnly")}</span>
            )}
          </>
        }
      />
      {/* The same window the chat draws under a message, given the page. */}
      <div className="border-border bg-background min-h-0 w-full min-w-0 flex-1 overflow-hidden rounded-2xl border shadow-sm">
        <BrowserWindow waitForFit browse={browse} control={{ canControl, canRemember, send }} />
      </div>
    </div>
  );
}
