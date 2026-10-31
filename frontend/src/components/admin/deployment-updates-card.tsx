"use client";

import { useEffect, useState } from "react";
import {
  ArrowUpRight,
  Check,
  Clock,
  Download,
  Loader2,
  RefreshCw,
  Server,
  ShieldCheck,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { version } from "../../../package.json";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  ListCard,
} from "@/components/ui";
import { useDeploymentUpdates } from "@/hooks/use-deployment-updates";
import { useReleaseUpdate } from "@/hooks/use-release-update";
import { isNewerRelease } from "@/lib/releases";

const STEPS = ["prepare", "backup", "apply", "check"] as const;
const RUNNING = new Set(["preparing", "draining", "backing_up", "applying", "checking"]);

export function DeploymentUpdatesCard() {
  const t = useTranslations("pages.adminUpdates");
  const { status, action } = useDeploymentUpdates();
  const release = useReleaseUpdate();
  const [schedule, setSchedule] = useState("");
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 30_000);
    return () => clearInterval(timer);
  }, []);
  const [confirm, setConfirm] = useState<"now" | "schedule" | null>(null);
  const state = status.data,
    operation = state?.operation;
  const latest = release.data?.latest;
  const available = latest && isNewerRelease(version, latest.version) ? latest : null;
  const running = !!operation && RUNNING.has(operation.phase);
  const busy =
    running || action.isPending || operation?.phase === "scheduled" || operation?.phase === "ready";
  const when = new Date(schedule).getTime() / 1000;
  const validSchedule = Number.isFinite(when) && when > now && when < now + 7 * 86400;
  const stage =
    operation?.phase === "succeeded"
      ? 4
      : operation?.phase === "checking"
        ? 3
        : ["applying", "draining", "backing_up", "scheduled", "ready"].includes(
              operation?.phase ?? "",
            )
          ? 2
          : 0;
  return (
    <ListCard title={t("title")} counted={t("hint")}>
      <div className="space-y-5 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="flex items-center gap-2 font-medium">
              <Server className="size-4" />
              {t("installed", { version })}
            </p>
            <p className="text-muted-foreground mt-1 text-sm">
              {available
                ? t("available", { version: available.version })
                : release.isPending
                  ? t("loading")
                  : release.isError
                    ? t("releaseUnavailable")
                    : t("latestInstalled")}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("refresh")}
            onClick={() => {
              void status.refetch();
              void release.refetch();
            }}
          >
            <RefreshCw className="size-4" />
          </Button>
        </div>
        {available ? (
          <a
            className="inline-flex items-center gap-1 text-sm underline underline-offset-4"
            href={available.url}
            target="_blank"
            rel="noreferrer"
          >
            {t("changelog")}
            <ArrowUpRight className="size-3.5" />
          </a>
        ) : null}
        <ol className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {STEPS.map((step, index) => (
            <li
              key={step}
              className="border-border flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
            >
              <span className="bg-muted flex size-6 shrink-0 items-center justify-center rounded-full text-xs">
                {stage > index ? <Check className="size-3.5" /> : index + 1}
              </span>
              {t(`steps.${step}`)}
            </li>
          ))}
        </ol>
        <p className="text-muted-foreground text-sm">{t("requirements")}</p>
        <p className="text-muted-foreground text-sm">{t("downtime")}</p>
        {status.isError ? (
          <p role="status" className="text-sm">
            {running ? t("reconnecting") : t("statusUnavailable")}
          </p>
        ) : null}
        {state && (!state.configured || !state.reachable) ? (
          <div className="bg-muted/40 space-y-2 rounded-lg p-3 text-sm">
            <p className="font-medium">{state.configured ? t("agentOffline") : t("setupTitle")}</p>
            <p className="text-muted-foreground">{t("setupHint")}</p>
            <a
              className="inline-flex items-center gap-1 underline underline-offset-4"
              target="_blank"
              rel="noreferrer"
              href="https://github.com/vstorm-co/agenticos/tree/main/deploy/updater"
            >
              {t("setupGuide")}
              <ArrowUpRight className="size-3.5" />
            </a>
          </div>
        ) : null}
        {operation ? (
          <div className="border-border space-y-2 rounded-lg border p-3 text-sm" aria-live="polite">
            <div className="flex items-center gap-2 font-medium">
              {running ? (
                <Loader2 className="size-4 animate-spin" />
              ) : operation.phase === "succeeded" ? (
                <ShieldCheck className="size-4" />
              ) : (
                <Clock className="size-4" />
              )}
              {operation.version} · {t(`phases.${operation.phase}`)}
            </div>
            {operation.scheduled_for && operation.phase === "scheduled" ? (
              <p>{new Date(operation.scheduled_for * 1000).toLocaleString()}</p>
            ) : null}
            {operation.backup_id ? (
              <p className="text-muted-foreground">
                {t("backupSaved")} <code>{operation.backup_id}</code>
              </p>
            ) : null}
            {operation.reason ? (
              <p role="alert">{t("failure", { reason: operation.reason })}</p>
            ) : null}
            {operation.phase === "failed" ? (
              <p className="text-muted-foreground">{t("recovery")}</p>
            ) : null}
          </div>
        ) : null}
        {action.isError ? (
          <p role="alert" className="text-destructive text-sm">
            {t("actionFailed")}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          {available && !busy ? (
            <Button
              type="button"
              disabled={!state?.reachable || action.isPending}
              onClick={() =>
                action.mutate({
                  kind: "prepare",
                  payload: { version: available.version.replace(/^v/, "") },
                })
              }
            >
              <Download className="size-4" />
              {t("prepare")}
            </Button>
          ) : null}
          {operation?.phase === "ready" ? (
            <>
              <Button type="button" disabled={action.isPending} onClick={() => setConfirm("now")}>
                {t("updateNow")}
              </Button>
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  type="datetime-local"
                  aria-label={t("scheduleTime")}
                  value={schedule}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") event.preventDefault();
                  }}
                  onChange={(event) => setSchedule(event.target.value)}
                  className="w-auto"
                />
                <Button
                  type="button"
                  variant="outline"
                  disabled={!validSchedule || action.isPending}
                  onClick={() => setConfirm("schedule")}
                >
                  <Clock className="size-4" />
                  {t("schedule")}
                </Button>
              </div>
            </>
          ) : null}
          {operation && ["ready", "scheduled"].includes(operation.phase) ? (
            <Button
              type="button"
              variant="ghost"
              disabled={action.isPending}
              onClick={() => action.mutate({ kind: "cancel", payload: { id: operation.id } })}
            >
              {t("cancel")}
            </Button>
          ) : null}
          {state?.pipeline_url ? (
            <Button type="button" variant="outline" asChild>
              <a href={state.pipeline_url} target="_blank" rel="noreferrer">
                {t("pipeline")}
                <ArrowUpRight className="size-4" />
              </a>
            </Button>
          ) : null}
        </div>
        <Dialog
          open={confirm !== null}
          onOpenChange={(open) => {
            if (!open) setConfirm(null);
          }}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t("confirmTitle")}</DialogTitle>
              <DialogDescription>{t("confirmHint")}</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setConfirm(null)}>
                {t("cancel")}
              </Button>
              <Button
                type="button"
                disabled={
                  !operation || action.isPending || (confirm === "schedule" && !validSchedule)
                }
                onClick={() => {
                  if (!operation) return;
                  action.mutate({
                    kind: "apply",
                    payload: {
                      id: operation.id,
                      scheduled_for: confirm === "schedule" ? when : null,
                    },
                  });
                  setConfirm(null);
                }}
              >
                {confirm === "schedule" ? t("schedule") : t("updateNow")}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </ListCard>
  );
}
