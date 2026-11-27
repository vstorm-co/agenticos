"use client";

import { useEffect, useState } from "react";
import { Clock3, Globe, Monitor, MoreHorizontal, RefreshCw, Square } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
} from "@/components/ui";
import { useChanged } from "@/hooks/use-changed";
import { useLiveConversationEnvironment } from "@/hooks/use-live-conversation-environment";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { BrowserWindow } from "./browser-window";

interface Props {
  conversationId: string;
  environment: ConversationEnvironment;
  visible: boolean;
  onState: (value: ConversationEnvironment) => Promise<void>;
  onStart: () => Promise<ConversationEnvironment>;
  onEnd: () => Promise<void>;
  onRefresh: () => Promise<void>;
  isStarting: boolean;
  isEnding: boolean;
}

/** A persistent environment's view; only explicit Start/End changes its lifetime. */
export function ConversationEnvironmentView(props: Props) {
  return (
    <EnvironmentView
      key={`${props.conversationId}:${props.environment.agent_id}:${props.environment.id}:${props.environment.execution_target}`}
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
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [action, setAction] = useState<"start" | "end" | "refresh" | null>(null);
  const [failure, setFailure] = useState<"start" | "end" | "state" | "refresh" | null>(null);
  const [startRefusal, setStartRefusal] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
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

  if (useChanged(visible) && !visible) setOptionsOpen(false);

  async function changeLifetime(next: "start" | "end") {
    setAction(next);
    setFailure(null);
    setStartRefusal(null);
    setChecked(false);
    try {
      if (next === "start") {
        const result = await onStart();
        if (result.refusal !== null || !["starting", "ready"].includes(result.state)) {
          setStartRefusal(result.refusal?.message ?? null);
          setFailure("start");
        }
      } else {
        await onEnd();
        setConfirmEnd(false);
      }
    } catch {
      setFailure(next);
    } finally {
      setAction(null);
    }
  }

  async function refresh() {
    setAction("refresh");
    setFailure(null);
    setStartRefusal(null);
    setChecked(false);
    try {
      await onRefresh();
      setChecked(true);
    } catch {
      setFailure("refresh");
    } finally {
      setAction(null);
    }
  }

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
  const endAllowed = visible && canEnd;
  if (useChanged(endAllowed) && !endAllowed) setConfirmEnd(false);
  const retryStream =
    authority.state === "ready" && ["unavailable", "malformed", "forbidden"].includes(live.status);
  const phase =
    live.status === "forbidden"
      ? "forbidden"
      : authority.state === "expired" || live.status === "gone"
        ? "expired"
        : authority.state === "failed" || blocked
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

  const lifetime =
    authority.session_lifetime === "run"
      ? t("runLifetime")
      : authority.idle_seconds % 60 === 0
        ? t("idleMinutes", { minutes: authority.idle_seconds / 60 })
        : t("idleSeconds", { seconds: authority.idle_seconds });
  const refreshButton = (
    <IconButton
      type="button"
      aria-label={t("refresh")}
      title={t("refresh")}
      className="size-8 shrink-0 pointer-coarse:size-11"
      disabled={busy}
      aria-busy={action === "refresh"}
      onClick={() => void refresh()}
    >
      <RefreshCw className={action === "refresh" ? "size-4 animate-spin" : "size-4"} aria-hidden />
    </IconButton>
  );
  const controlHint =
    authority.control === "agent"
      ? t("agentDriving")
      : authority.control === "human"
        ? t("humanDriving")
        : authority.can_control
          ? t("canTakeOver")
          : t("watchOnly");
  const menuItems = (
    <>
      <DropdownMenuLabel className="text-muted-foreground max-w-72 space-y-1 text-xs font-normal whitespace-normal">
        <span className="text-foreground flex items-center gap-2 font-medium">
          <Clock3 className="size-3.5" aria-hidden />
          {t("lifetime")}
        </span>
        <span className="block leading-relaxed">{lifetime}</span>
        {hasView && <span className="block border-t pt-2 leading-relaxed">{controlHint}</span>}
      </DropdownMenuLabel>
      <DropdownMenuItem disabled={busy} onSelect={() => void refresh()}>
        <RefreshCw
          className={action === "refresh" ? "size-4 animate-spin" : "size-4"}
          aria-hidden
        />
        {t("refresh")}
      </DropdownMenuItem>
      {canEnd && (
        <DropdownMenuItem disabled={busy} onSelect={() => setConfirmEnd(true)}>
          <Square className="size-4" aria-hidden />
          {t("end")}
        </DropdownMenuItem>
      )}
      <DropdownMenuSeparator />
    </>
  );

  return (
    <div
      hidden={!visible}
      inert={!visible}
      className={
        visible ? "flex h-full min-h-0 min-w-0 flex-col" : "hidden h-full min-h-0 min-w-0 flex-col"
      }
    >
      {!hasView && (
        <div className="bg-muted/25 flex min-w-0 shrink-0 items-center gap-2 border-b px-2 py-1.5">
          <Icon className="text-muted-foreground size-4 shrink-0" aria-hidden />
          <p className="min-w-0 flex-1 truncate text-xs font-medium">
            {t(authority.kind === "desktop" ? "desktopTitle" : "browserTitle")}
          </p>
          {refreshButton}
          <DropdownMenu open={visible && optionsOpen} onOpenChange={setOptionsOpen}>
            <DropdownMenuTrigger asChild>
              <IconButton
                aria-label={t("options")}
                title={t("options")}
                className="size-8 pointer-coarse:size-11"
              >
                <MoreHorizontal className="size-4" aria-hidden />
              </IconButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">{menuItems}</DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
      {checked && (
        <p role="status" className="text-muted-foreground border-b px-3 py-1.5 text-xs">
          {t("checked", { status: hasView ? t("ready") : t(`phase.${phase}.title`) })}
        </p>
      )}
      {failure !== null && (failure !== "end" || !confirmEnd) && (
        <p role="alert" className="text-destructive border-b px-3 py-2 text-sm">
          {failure === "start" && startRefusal !== null ? startRefusal : t(`failure.${failure}`)}
        </p>
      )}
      {live.browse !== null &&
        authority.state === "ready" &&
        authority.refusal === null &&
        live.status !== "forbidden" && (
          <div
            hidden={!hasView}
            inert={!hasView}
            className={hasView ? "min-h-0 min-w-0 flex-1" : "hidden min-h-0 min-w-0 flex-1"}
          >
            <BrowserWindow
              surface={environment.kind}
              controlState={authority.control}
              tabs={authority.kind === "browser" ? live.tabs : null}
              onActivateTab={live.activateTab}
              selectingTab={live.selectingTab}
              active={visible && hasView}
              browse={
                authority.kind === "desktop" ? { ...live.browse, navigable: false } : live.browse
              }
              menuItems={menuItems}
              control={
                authority.can_control && authority.control !== "agent"
                  ? { canControl: true, canRemember: false, send: live.send }
                  : null
              }
            />
          </div>
        )}
      {!hasView && (
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
        open={endAllowed && confirmEnd}
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
