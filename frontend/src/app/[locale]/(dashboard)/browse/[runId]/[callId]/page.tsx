"use client";

import { use, useState } from "react";
import { Hand, MonitorPlay, Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { AddressBar, LiveBadge, Outcome, StepTimeline } from "@/components/chat/browser-view";
import { LiveViewport } from "@/components/chat/live-viewport";
import { EmptyState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { useLiveBrowse } from "@/hooks/use-live-browse";
import { isRunning } from "@/lib/browse";
import { useAuthStore } from "@/stores";

interface PageProps {
  params: Promise<{ runId: string; callId: string }>;
}

/**
 * One browse, live, from wherever it was started (#2128).
 *
 * The address a channel posts and the chat links to: the agent's browser as it
 * is now, what it has done, and - for the person the run acts for or someone who
 * may edit the agent - a way to take it over. Taking over waits for the step in
 * flight, then the page is theirs: click, type, scroll. Handing it back lets the
 * agent carry on from the page as they left it. What they type is passed to the
 * page and never recorded.
 */
export default function LiveBrowsePage({ params }: PageProps) {
  const { runId, callId } = use(params);
  const t = useTranslations("browse");
  const { browse, task, canControl, status, send } = useLiveBrowse(runId, callId);
  const user = useAuthStore((state) => state.user);
  const me = user?.full_name || user?.email || "";
  const [asked, setAsked] = useState(false);

  if (status === "gone" || status === "forbidden" || status === "unavailable") {
    return (
      <EmptyState icon={MonitorPlay} title={t(`${status}Title`)} description={t(`${status}Body`)} />
    );
  }
  if (status === "connecting" || browse === null) {
    return <LoadingState variant="skeleton-panel" rows={3} />;
  }

  const running = isRunning(browse);
  const holding = Boolean(browse.heldBy) && browse.heldBy === me;
  const someoneElse = Boolean(browse.heldBy) && !holding;
  const waitingForStep = asked && !browse.heldBy && running;

  const takeOver = () => {
    setAsked(true);
    send({ type: "take_over" });
  };
  const giveBack = () => {
    setAsked(false);
    send({ type: "give_back" });
  };

  // On a phone the person arriving from a link came to act, so what the browse
  // needs and the control that answers it come before the picture; on a wide
  // screen the picture takes the left column and the rest sits beside it.
  return (
    <div className="mx-auto grid max-w-7xl gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-[auto_1fr]">
      <section className="min-w-0 space-y-3 lg:row-span-2">
        <div className="flex items-center gap-2">
          <AddressBar url={browse.url} className="flex-1" />
          <LiveBadge browse={browse} />
        </div>
        <LiveViewport browse={browse} holding={holding} onCommand={send} />
        {holding && <p className="text-muted-foreground text-xs">{t("holdingHint")}</p>}
      </section>

      <div className="order-first min-w-0 space-y-5 lg:order-none">
        <div className="space-y-1">
          <h1 className="text-foreground text-lg font-semibold">{t("title")}</h1>
          <p className="text-foreground/80 text-sm leading-relaxed">{task || browse.goal}</p>
        </div>

        {browse.needs && running && (
          <div className="rounded-xl bg-amber-500/10 p-3">
            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
              {t("needsYou")}
            </p>
            {/* Model-written - rendered as text. */}
            <p className="text-foreground/80 mt-1 text-sm">{browse.needs}</p>
          </div>
        )}

        {running && canControl && (
          <div className="space-y-2">
            {holding ? (
              <Button className="w-full" onClick={giveBack}>
                <Undo2 aria-hidden />
                {t("giveBack")}
              </Button>
            ) : someoneElse ? (
              <p className="text-muted-foreground text-sm">
                {t("heldBy", { name: browse.heldBy ?? "" })}
              </p>
            ) : (
              <Button className="w-full" onClick={takeOver} disabled={waitingForStep}>
                <Hand aria-hidden />
                {waitingForStep ? t("takingOver") : t("takeOver")}
              </Button>
            )}
            {!holding && !someoneElse && (
              <p className="text-muted-foreground text-xs">{t("takeOverHint")}</p>
            )}
          </div>
        )}
        {running && !canControl && (
          <p className="text-muted-foreground text-sm">{t("watchOnly")}</p>
        )}

        <Outcome browse={browse} />
      </div>

      {browse.steps.length > 0 && (
        <section className="min-w-0 space-y-2.5">
          <h2 className="text-muted-foreground text-xs font-medium">{t("steps")}</h2>
          <StepTimeline browse={browse} />
        </section>
      )}
    </div>
  );
}
