"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { resultReasons } from "@/components/evals/suites/suite-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useAgentEnvironments } from "@/hooks";
import { isPromotionBlocked } from "@/hooks/use-agent-environments";
import { usePromotionGate, useRunPromotionGate } from "@/hooks/use-promotion-gate";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { qk } from "@/lib/query-keys";
import type { AgentEnvironment } from "@/types/agents";
import type { GuardState, PromotionGuard } from "@/types/promotion-gate";

/** The badge a guard's state wears: green lets the version through, red stops it. */
const STATE_TONE: Record<GuardState, "success" | "destructive" | "warning" | "secondary"> = {
  passed: "success",
  failed: "destructive",
  inconclusive: "warning",
  skipped: "warning",
  error: "warning",
  checking: "secondary",
  stale: "warning",
  unchecked: "warning",
  paused: "warning",
  unpinned: "warning",
};

/** States a run of the guard on the version would change. */
const RUNNABLE: ReadonlySet<GuardState> = new Set([
  "failed",
  "inconclusive",
  "skipped",
  "error",
  "stale",
  "unchecked",
]);

/** The shortest reason a person can type that still says something. */
const MIN_REASON = 10;

/** What one guard's state means, in a line, with the result's own words where it has them. */
function GuardDetail({ guard }: { guard: PromotionGuard }) {
  const t = useTranslations("promotionGate");
  const tSuites = useTranslations("evals.suites");
  const locale = useLocale();
  const result = guard.result;
  const told =
    result && (guard.state === result.status || result.status === "baseline_set")
      ? resultReasons(result, tSuites, locale)
      : [];
  const lines =
    guard.state === "paused"
      ? [
          guard.paused_reason
            ? tSuites(`paused.${guard.paused_reason}`)
            : tSuites("paused.byPerson"),
        ]
      : told.length > 0
        ? told
        : [t(`hint.${guard.state}`)];
  return (
    <ul className="text-muted-foreground space-y-0.5 text-xs">
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

/**
 * Promoting a version onto an environment its eval suites guard.
 *
 * Every guard is listed with where it stands on the version, so "why can I not
 * promote" is answered on the screen that refuses it. A guard that has not
 * checked the version - or checked another dataset version of it - can be run
 * from here, beside the version the environment serves now. Somebody allowed to
 * may promote anyway, saying why; the reason goes to the audit log and onto the
 * version, and the guards' owners hear of it.
 */
export function PromotionDialog({
  agentId,
  environment,
  versionId,
  onClose,
}: {
  agentId: string;
  environment: AgentEnvironment;
  versionId: string;
  onClose: () => void;
}) {
  const t = useTranslations("promotionGate");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { gate, isLoading, error, refetch } = usePromotionGate(agentId, environment.id, versionId);
  const run = useRunPromotionGate(agentId);
  const { promote } = useAgentEnvironments(agentId);
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();

  async function submit(overrideReason?: string) {
    try {
      await promote.mutateAsync({ environmentId: environment.id, versionId, overrideReason });
      onClose();
    } catch (error) {
      // Any other refusal is the mutation's toast. A gate that moved since it
      // was read is shown again as it is now.
      if (isPromotionBlocked(error)) {
        await queryClient.invalidateQueries({
          queryKey: qk.evalSuites.gate(agentId, environment.id, versionId),
        });
      }
    }
  }

  const runnable = gate?.guards.some((guard) => RUNNABLE.has(guard.state)) ?? false;
  const reasonOk = reason.trim().length >= MIN_REASON;
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>
            {t("title", { version: gate?.version ?? "…", name: environment.name })}
          </DialogTitle>
          <DialogDescription>{t("body", { name: environment.name })}</DialogDescription>
        </DialogHeader>
        {error && !gate ? (
          <div role="alert" className="space-y-2 text-sm">
            <p className="text-destructive">{t("readFailed")}</p>
            <p className="text-muted-foreground text-xs">{getErrorMessage(error, tErrors)}</p>
            <Button size="sm" variant="outline" onClick={() => void refetch()}>
              {t("retry")}
            </Button>
          </div>
        ) : isLoading || !gate ? (
          <Spinner />
        ) : (
          <div className="space-y-4">
            <ul className="divide-y rounded-md border">
              {gate.guards.map((guard) => (
                <li key={guard.suite_id} className="space-y-1 px-3 py-2 text-sm">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-medium">{guard.suite_name}</span>
                    <Badge variant={STATE_TONE[guard.state]}>{t(`state.${guard.state}`)}</Badge>
                  </div>
                  <GuardDetail guard={guard} />
                </li>
              ))}
            </ul>
            {gate.passing ? (
              <p className="text-success flex items-center gap-2 text-sm">
                <ShieldCheck className="h-4 w-4" aria-hidden />
                {t("passing", { version: gate.version })}
              </p>
            ) : (
              gate.can_override && (
                <div
                  role="group"
                  aria-label={t("overrideTitle")}
                  className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3"
                >
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <ShieldAlert className="h-4 w-4" aria-hidden />
                    {t("overrideTitle")}
                  </p>
                  <p className="text-muted-foreground text-xs">{t("overrideBody")}</p>
                  <Label htmlFor="override-reason">{t("overrideReason")}</Label>
                  <Textarea
                    id="override-reason"
                    value={reason}
                    maxLength={2000}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder={t("overridePlaceholder")}
                  />
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={!reasonOk || promote.isPending}
                    onClick={() => void submit(reason.trim())}
                  >
                    {t("overrideSubmit")}
                  </Button>
                </div>
              )
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {tc("cancel")}
          </Button>
          {gate && runnable && (
            <Button
              variant="outline"
              disabled={run.isPending}
              onClick={() => run.mutate({ environmentId: environment.id, versionId })}
            >
              {t("run", { version: gate.version })}
            </Button>
          )}
          <Button disabled={!gate?.passing || promote.isPending} onClick={() => void submit()}>
            {t("promote")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Promote through the gate where an environment has one, and straight through
 * where it does not - which is exactly what an unguarded environment did before.
 */
export function useGuardedPromotion(agentId: string, environments: AgentEnvironment[]) {
  const { promote } = useAgentEnvironments(agentId);
  const [asked, setAsked] = useState<{ environment: AgentEnvironment; versionId: string } | null>(
    null,
  );
  function request(environmentId: string, versionId: string) {
    const environment = environments.find((candidate) => candidate.id === environmentId);
    if (environment && environment.guard_suite_ids.length > 0) {
      setAsked({ environment, versionId });
    } else {
      promote.mutate({ environmentId, versionId });
    }
  }
  const dialog = asked ? (
    <PromotionDialog
      agentId={agentId}
      environment={asked.environment}
      versionId={asked.versionId}
      onClose={() => setAsked(null)}
    />
  ) : null;
  return { request, dialog, promoting: promote.isPending };
}
