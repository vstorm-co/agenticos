"use client";

import { useEffect, useState } from "react";
import { Globe, Monitor, RefreshCw, Square } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, ConfirmDialog } from "@/components/ui";
import { useLiveConversationEnvironment } from "@/hooks/use-live-conversation-environment";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { BrowserWindow } from "./browser-window";

interface Props {
  conversationId: string;
  environment: ConversationEnvironment;
  visible: boolean;
  onState: (value: ConversationEnvironment) => Promise<void>;
  onStart: () => Promise<void>;
  onEnd: () => Promise<void>;
  onRefresh: () => void;
  isStarting: boolean;
  isEnding: boolean;
}

/** A persistent environment's view; only explicit Start/End changes its lifetime. */
export function ConversationEnvironmentView(props: Props) {
  return (
    <EnvironmentView
      key={`${props.conversationId}:${props.environment.agent_id}:${props.environment.id}:${props.environment.execution_target}:${props.visible}`}
      {...props}
    />
  );
}

function EnvironmentView({
  conversationId,
  environment,
  visible,
  onState,
  onStart,
  onEnd,
  onRefresh,
  isStarting,
  isEnding,
}: Props) {
  const t = useTranslations("chat.environmentView");
  const live = useLiveConversationEnvironment(conversationId, environment, visible);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [action, setAction] = useState<"start" | "end" | null>(null);
  const [failure, setFailure] = useState<"start" | "end" | "state" | null>(null);
  const authority = live.environment ?? environment;
  const busy = isStarting || isEnding || action !== null;

  useEffect(() => {
    if (!visible || !live.environment) return;
    let active = true;
    void onState(live.environment).catch(() => {
      if (active) setFailure("state");
    });
    return () => {
      active = false;
    };
  }, [visible, live.environment, onState]);

  async function changeLifetime(next: "start" | "end") {
    setAction(next);
    setFailure(null);
    try {
      await (next === "start" ? onStart() : onEnd());
      if (next === "end") setConfirmEnd(false);
    } catch {
      setFailure(next);
    } finally {
      setAction(null);
    }
  }

  if (!visible) return null;

  const hasView =
    authority.state === "ready" &&
    authority.refusal === null &&
    live.status === "live" &&
    live.browse !== null;
  const terminal = authority.state === "expired" || authority.state === "failed";
  const blocked = authority.refusal !== null;
  const canStart =
    live.status !== "forbidden" &&
    (authority.state === "not_started" || terminal) &&
    !["capability_not_enabled", "backend_not_supported", "local_device_required"].some(
      (code) => authority.refusal?.code === code,
    );
  const canEnd =
    authority.id !== null && authority.state !== "expired" && live.status !== "forbidden";
  const retryStream =
    authority.state === "ready" && ["unavailable", "malformed"].includes(live.status);
  const phase =
    live.status === "forbidden"
      ? "forbidden"
      : authority.state === "expired" || live.status === "gone"
        ? "expired"
        : authority.state === "failed"
          ? "failed"
          : authority.state === "not_started"
            ? "notStarted"
            : authority.state === "starting"
              ? "starting"
              : live.status === "malformed"
                ? "malformed"
                : live.status === "unavailable"
                  ? "disconnected"
                  : "connecting";
  const Icon = authority.kind === "browser" ? Globe : Monitor;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        {authority.state === "ready" && (
          <p className="text-muted-foreground min-w-0 text-xs">
            {authority.control === "agent"
              ? t("agentDriving")
              : authority.control === "human"
                ? t("humanDriving")
                : authority.can_control
                  ? t("canTakeOver")
                  : t("watchOnly")}
          </p>
        )}
        <div className="ml-auto flex shrink-0 flex-wrap gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="touch:min-h-11"
            disabled={busy}
            onClick={onRefresh}
          >
            <RefreshCw className="size-3.5" aria-hidden />
            {t("refresh")}
          </Button>
          {canEnd && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="touch:min-h-11"
              disabled={busy}
              onClick={() => setConfirmEnd(true)}
            >
              <Square className="size-3.5" aria-hidden />
              {t("end")}
            </Button>
          )}
        </div>
      </div>
      <p className="text-muted-foreground border-b px-3 py-2 text-xs">
        {authority.session_lifetime === "run"
          ? t("runLifetime")
          : authority.idle_seconds % 60 === 0
            ? t("idleMinutes", { minutes: authority.idle_seconds / 60 })
            : t("idleSeconds", { seconds: authority.idle_seconds })}
      </p>
      {failure !== null && (failure !== "end" || !confirmEnd) && (
        <p role="alert" className="text-destructive border-b px-3 py-2 text-sm">
          {t(`failure.${failure}`)}
        </p>
      )}
      {hasView && live.browse !== null ? (
        <div className="min-h-0 min-w-0 flex-1">
          <BrowserWindow
            surface={environment.kind}
            browse={
              authority.kind === "desktop" ? { ...live.browse, navigable: false } : live.browse
            }
            control={
              authority.can_control && authority.control !== "agent"
                ? { canControl: true, canRemember: false, send: live.send }
                : null
            }
          />
        </div>
      ) : (
        <div
          className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 overflow-y-auto p-5 text-center sm:p-8"
          aria-busy={phase === "starting" || (phase === "connecting" && !blocked)}
        >
          <Icon className="text-muted-foreground size-8 shrink-0" aria-hidden />
          <div className="max-w-sm space-y-2">
            <h2 className="text-base font-medium">{t(`phase.${phase}.title`)}</h2>
            <p className="text-muted-foreground text-sm leading-relaxed">
              {authority.refusal?.message ?? t(`phase.${phase}.description`)}
            </p>
          </div>
          {canStart && (
            <Button
              type="button"
              className="touch:min-h-11"
              loading={isStarting || action === "start"}
              disabled={busy}
              onClick={() => void changeLifetime("start")}
            >
              {t(authority.state === "not_started" ? "start" : "startNew")}
            </Button>
          )}
          {retryStream && (
            <Button
              type="button"
              variant="outline"
              className="touch:min-h-11"
              disabled={busy}
              onClick={live.retry}
            >
              {t("retry")}
            </Button>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirmEnd}
        onOpenChange={(open) => {
          if (!busy) setConfirmEnd(open);
        }}
        title={t("confirmTitle")}
        description={t("confirmDescription")}
        confirmLabel={t("end")}
        destructive
        loading={isEnding || action === "end"}
        onConfirm={() => changeLifetime("end")}
      >
        {failure === "end" && (
          <p role="alert" className="text-destructive text-sm">
            {t("failure.end")}
          </p>
        )}
      </ConfirmDialog>
    </div>
  );
}
