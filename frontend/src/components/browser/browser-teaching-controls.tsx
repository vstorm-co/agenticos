"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { BookOpenCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useBrowserProcedureTeaching } from "@/hooks/use-browser-procedure-teaching";
import {
  useBrowserProcedureTeachingAudience,
  useBrowserProcedureTeachingPolicy,
  useBrowserProcedureTeachingRun,
} from "@/hooks/use-browser-procedure-teaching-settings";
import { isBrowserProcedureTeachingAudienceCurrent } from "@/lib/browser-procedure-teaching-api";
import {
  isBrowserProcedureTeachingId,
  browserProcedureTeachingDeadlineLive,
} from "@/lib/browser-procedure-teaching-review";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { ROUTES } from "@/lib/constants";
import { isRunning, type Browse } from "@/lib/browse";
import type { BrowserProcedureTeaching } from "@/types/browser-procedure-teaching";
import { BrowserTeachingStart } from "./browser-teaching-start";
import { BrowserTeachingPreference } from "./browser-teaching-preference";
import { TeachingError, BrowserProcedureTeachingStatus } from "./browser-teaching-status";

export function BrowserTeachingControls({
  browse,
  canControl,
}: {
  browse: Browse;
  canControl: boolean;
}) {
  const audience = useBrowserProcedureTeachingAudience();
  if (!browse.runId || !browse.tabId || browse.outputProtected) return null;
  return (
    <TeachingControls
      key={JSON.stringify([
        audience.actor,
        audience.organization,
        browse.runId,
        browse.callId,
        browse.tabId,
      ])}
      browse={browse}
      canControl={canControl}
    />
  );
}
function TeachingControls({ browse, canControl }: { browse: Browse; canControl: boolean }) {
  const t = useTranslations("browserProcedureTeaching");
  const [open, setOpen] = useState(false);
  const notification = browse.teachingSessionId ?? null;
  const [selection, setSelection] = useState({ notification, id: notification });
  if (selection.notification !== notification) {
    setSelection({ notification, id: notification });
  }
  const id = selection.notification === notification ? selection.id : notification;
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        aria-label={t("controlsTitle")}
        className="h-8 gap-1 px-2"
      >
        <BookOpenCheck className="size-4" aria-hidden />
        <span className="hidden @min-[640px]/browser-window:inline">
          {browse.teachingStatus === "recording" ? t("recording") : t("teach")}
        </span>
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
          <DialogHeader>
            <DialogTitle>{t("controlsTitle")}</DialogTitle>
            <DialogDescription>{t("captureDescription")}</DialogDescription>
          </DialogHeader>
          {open && (
            <TeachingPanel
              key={id ?? "new"}
              browse={browse}
              canControl={canControl}
              id={id}
              select={(id) => setSelection({ notification, id })}
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
function TeachingPanel({
  browse,
  canControl,
  id,
  select,
}: {
  browse: Browse;
  canControl: boolean;
  id: string | null;
  select: (id: string | null) => void;
}) {
  const t = useTranslations("browserProcedureTeaching");
  const locale = useLocale();
  const audience = useBrowserProcedureTeachingAudience();
  const state = useBrowserProcedureTeaching(id, browse.teachingRevision);
  const policy = useBrowserProcedureTeachingPolicy();
  const run = useBrowserProcedureTeachingRun(browse.runId!, true);
  const session =
    state.session &&
    state.session.run_id === browse.runId &&
    state.session.call_id === browse.callId &&
    state.session.tab_id === browse.tabId
      ? state.session
      : undefined;
  const holding =
    canControl &&
    isRunning(browse) &&
    browse.heldById === audience.actor &&
    !!browse.takeoverId &&
    isBrowserProcedureTeachingId(browse.takeoverId);
  const admission =
    !!policy.data?.enabled && policy.data.deployment_enabled && !!run.data?.agent_id;
  const busy = useRef(false);
  async function act(action: "pause" | "resume" | "stop") {
    if (!session || busy.current || (action === "resume" && !holding)) return;
    busy.current = true;
    try {
      await state.command.mutateAsync(
        action === "stop"
          ? { action, session }
          : {
              action: "change",
              session,
              body: action === "pause" ? { action } : { action, takeover_id: browse.takeoverId! },
            },
      );
    } catch {
      /* The mutation's translated refusal remains visible. */
    } finally {
      busy.current = false;
    }
  }
  function onStarted(next: BrowserProcedureTeaching) {
    if (isBrowserProcedureTeachingAudienceCurrent(audience)) select(next.id);
  }
  return (
    <>
      {session ? (
        <section className="space-y-3" data-tour="teaching-capture">
          <h3 className="font-medium break-words">{session.title || t("expiredCapture")}</h3>
          <BrowserProcedureTeachingStatus session={session} />
          <p className="text-muted-foreground text-sm">
            {t("capturedSteps", { count: session.events.length })}
          </p>
          <div className="flex flex-wrap gap-2">
            {session.source === "manual" && session.status === "recording" && (
              <Button
                variant="outline"
                disabled={state.command.isPending}
                onClick={() => void act("pause")}
              >
                {t("pause")}
              </Button>
            )}
            {session.source === "manual" && session.status === "paused" && (
              <Button
                disabled={
                  !holding ||
                  !browserProcedureTeachingDeadlineLive(session.capture_ends_at, state.now) ||
                  state.command.isPending
                }
                onClick={() => void act("resume")}
              >
                {t("resume")}
              </Button>
            )}
            {(session.status === "recording" || session.status === "paused") && (
              <Button
                variant="outline"
                disabled={state.command.isPending}
                onClick={() => void act("stop")}
              >
                {session.source === "refinement" ? t("stopRefinement") : t("stopRecording")}
              </Button>
            )}
            <Button asChild variant="outline">
              <Link href={`/${locale}${ROUTES.SKILL_TEACHING(session.id)}`}>
                {t("reviewCapture")}
              </Link>
            </Button>
            {session.status !== "recording" && session.status !== "paused" && (
              <Button
                variant="outline"
                disabled={!holding || !admission}
                onClick={() => select(null)}
              >
                {t("newCapture")}
              </Button>
            )}
          </div>
          {session.status === "paused" && !holding && (
            <p className="text-muted-foreground text-sm">{t("takeOverRequired")}</p>
          )}
          {state.command.error && <TeachingError error={state.command.error} />}
          {state.pollingEnded && (
            <Button variant="outline" onClick={() => void state.refresh()}>
              {t("checkAgain")}
            </Button>
          )}
        </section>
      ) : id ? (
        <div className="space-y-2">
          <p role="status">{state.query.isPending ? t("loading") : t("captureUnavailable")}</p>
          <Button
            variant="outline"
            disabled={state.query.isFetching}
            onClick={() => void state.refresh()}
          >
            {t("checkAgain")}
          </Button>
        </div>
      ) : (
        <>
          {(policy.isPending || run.isPending) && <p role="status">{t("loading")}</p>}
          {(policy.error || run.error) && <TeachingError error={policy.error || run.error} />}
          {policy.data && !policy.data.deployment_enabled && (
            <p className="text-muted-foreground text-sm">{t("deploymentDisabled")}</p>
          )}
          {policy.data?.deployment_enabled && !policy.data.enabled && (
            <p className="text-muted-foreground text-sm">{t("organizationDisabled")}</p>
          )}
          <BrowserTeachingStart
            browse={browse}
            canStart={admission && holding}
            onStarted={onStarted}
          />
        </>
      )}
      {run.data?.agent_id && <BrowserTeachingPreference agentId={run.data.agent_id} />}
    </>
  );
}
