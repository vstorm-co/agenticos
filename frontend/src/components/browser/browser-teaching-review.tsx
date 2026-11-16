"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, ConfirmDialog } from "@/components/ui";
import { PageHeader } from "@/components/dashboard/page-header";
import { useBrowserTeaching } from "@/hooks/use-browser-teaching";
import { useTeachingAudience } from "@/hooks/use-browser-teaching-settings";
import { usePermissions } from "@/hooks/use-permissions";
import { clearTeachingAttempt, teachingAttemptKey } from "@/lib/browser-teaching-attempts";
import { teachingDeadlineLive, teachingDraftPending } from "@/lib/browser-teaching-review";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import { BrowserTeachingReviewForm } from "./browser-teaching-review-form";
import { BrowserTeachingPreference } from "./browser-teaching-preference";
import { TeachingError, TeachingStatus, TeachingTime } from "./browser-teaching-status";

export function BrowserTeachingReview({ sessionId }: { sessionId: string }) {
  const audience = useTeachingAudience();
  return (
    <TeachingReviewContent
      key={JSON.stringify([audience.actor, audience.organization, sessionId])}
      sessionId={sessionId}
    />
  );
}
function TeachingReviewContent({ sessionId }: { sessionId: string }) {
  const t = useTranslations("browserTeaching");
  const locale = useLocale();
  const state = useBrowserTeaching(sessionId);
  const { session } = state;
  const { can } = usePermissions();
  const [discard, setDiscard] = useState(false);
  const busy = useRef(false);
  const draftKey = teachingAttemptKey(state.audience, "propose", [sessionId]);
  useEffect(() => {
    if (session && session.generation_state !== "none") clearTeachingAttempt(draftKey);
  }, [session, draftKey]);
  async function act(action: "stop" | "discard") {
    if (!session || busy.current) return;
    busy.current = true;
    try {
      await state.command.mutateAsync({ action, session });
      setDiscard(false);
    } catch {
      /* The current scoped refusal is rendered without transport text. */
    } finally {
      busy.current = false;
    }
  }
  const canReview =
    session?.status === "review" &&
    (session.generation_state === "none" || session.generation_state === "refused") &&
    teachingDeadlineLive(session.expires_at, state.now) &&
    (session.source === "manual" || session.verified_success);
  const proposalAccess = can(Perm.skillsEdit) && can(Perm.runsView);
  return (
    <div className="flex min-w-0 flex-1 flex-col gap-5">
      <PageHeader
        title={session?.title || t("reviewTitle")}
        description={t("captureDescription")}
        secondaryActions={
          <Button asChild variant="outline">
            <Link href={`/${locale}${ROUTES.SKILLS_TEACHING}`}>{t("allCaptures")}</Link>
          </Button>
        }
      />
      {!session ? (
        <section className="space-y-3">
          <p role={state.query.isPending && state.ready ? "status" : "alert"}>
            {state.query.isPending && state.ready ? t("loading") : t("captureUnavailable")}
          </p>
          <Button
            variant="outline"
            disabled={!state.ready || state.query.isFetching}
            onClick={() => void state.refresh()}
          >
            {t("checkAgain")}
          </Button>
        </section>
      ) : (
        <>
          <section
            className="space-y-3 rounded-lg border p-4"
            aria-label={t("captureSummary")}
            data-tour="teaching-summary"
          >
            <TeachingStatus session={session} />
            <p className="text-muted-foreground text-sm break-words">
              {session.allowed_origins.join(", ")}
            </p>
            <p className="text-sm">
              {session.source === "manual"
                ? t("manualEvidence")
                : session.verified_success
                  ? t("completedEvidence")
                  : t("completionPending")}
            </p>
            {session.reason_code && (
              <p className="text-muted-foreground text-sm">{t(`reason.${session.reason_code}`)}</p>
            )}
            <p className="text-muted-foreground text-xs">
              {t("captureExpires")} <TeachingTime value={session.expires_at} />
            </p>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                disabled={state.query.isFetching || state.command.isPending}
                onClick={() => void state.refresh()}
              >
                {t("checkAgain")}
              </Button>
              {(session.status === "recording" || session.status === "paused") && (
                <Button
                  variant="outline"
                  disabled={state.command.isPending}
                  onClick={() => void act("stop")}
                >
                  {session.source === "manual" ? t("stopRecording") : t("stopRefinement")}
                </Button>
              )}
              {session.status !== "proposed" && session.status !== "discarded" && (
                <Button
                  variant="outline"
                  onClick={() => setDiscard(true)}
                  disabled={state.command.isPending}
                >
                  {t("discardCapture")}
                </Button>
              )}
            </div>
            {state.pollingEnded && teachingDraftPending(session) && (
              <p role="status" className="text-muted-foreground text-sm">
                {t("pollingEnded")}
              </p>
            )}
            {session.generation_state === "unknown" && (
              <p className="text-sm">{t("draftUnknown")}</p>
            )}
          </section>
          {state.command.error && <TeachingError error={state.command.error} />}
          <BrowserTeachingPreference agentId={session.agent_id} />
          {session.proposal_id && (
            <section className="space-y-3 rounded-lg border p-4" data-tour="teaching-proposal">
              <h2 className="font-medium">{t("proposalReady")}</h2>
              <p className="text-muted-foreground text-sm">{t("proposalDetail")}</p>
              {proposalAccess ? (
                <Button asChild>
                  <Link href={`/${locale}${ROUTES.SKILLS}`}>{t("openProposals")}</Link>
                </Button>
              ) : (
                <p className="text-sm">{t("proposalUnavailable")}</p>
              )}
            </section>
          )}
          {canReview ? (
            <BrowserTeachingReviewForm key={session.id} session={session} state={state} />
          ) : (
            session.events.length > 0 && (
              <section className="space-y-3" aria-label={t("capturedEvents")}>
                <h2 className="font-medium">{t("capturedEvents")}</h2>
                <p className="text-muted-foreground text-sm">{t("eventsValueFree")}</p>
                <ol className="space-y-2">
                  {session.events.map((event) => (
                    <li key={event.sequence} className="rounded-lg border p-3 text-sm">
                      <p>
                        {t("stepNumber", { number: event.sequence })} ·{" "}
                        {t(`action.${event.action}`)}
                      </p>
                      <p className="text-muted-foreground text-xs break-words">{event.origin}</p>
                    </li>
                  ))}
                </ol>
              </section>
            )
          )}
        </>
      )}
      <ConfirmDialog
        open={discard}
        onOpenChange={setDiscard}
        title={t("discardTitle")}
        description={t("discardDescription")}
        destructive
        confirmLabel={t("discardCapture")}
        loading={state.command.isPending}
        onConfirm={() => act("discard")}
      />
    </div>
  );
}
