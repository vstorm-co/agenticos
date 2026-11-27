"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FolderOpen } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useConversationEnvironments } from "@/hooks/use-conversation-environments";
import type { EnvironmentExecutionTarget } from "@/lib/conversation-environments-api";
import { isRunning, type Browse } from "@/lib/browse";
import { useSourcesPanelStore } from "@/stores/sources-panel-store";
import { useRequiredChatWorkspace, type WorkspaceEnvironment } from "./chat-workspace-context";
import { ChatWorkspaceFrame } from "./chat-workspace-frame";
import { ConversationEnvironmentView } from "./conversation-environment-view";

interface Props {
  conversationId: string | null;
  agentId: string;
  panels: readonly WorkspaceEnvironment[];
  browses: readonly Browse[];
  target: EnvironmentExecutionTarget;
  buttonSlot: HTMLElement | null;
  prepareConversation: () => Promise<string | null>;
  preparing: boolean;
}

/** One click restores the last available workspace pane; viewing never provisions a provider. */
export function ConversationEnvironments({
  conversationId,
  agentId,
  panels,
  browses,
  target,
  buttonSlot,
  prepareConversation,
  preparing,
}: Props) {
  const t = useTranslations("chat.workspace");
  const status = useTranslations("chat.environmentView");
  const common = useTranslations("common");
  const workspace = useRequiredChatWorkspace();
  const trigger = useRef<HTMLButtonElement>(null);
  const [opening, setOpening] = useState(false);
  const [failed, setFailed] = useState(false);
  const selected = workspace.environment;
  const visible =
    selected !== null && workspace.activePanel === selected && panels.includes(selected);
  const browserActive =
    workspace.browserId !== null &&
    workspace.activePanel === "browser" &&
    panels.includes("browser");
  const environments = useConversationEnvironments(
    conversationId,
    agentId,
    opening || visible || browserActive,
    target,
  );
  const { refresh } = environments;
  const activityEnvironmentId = browses.find(
    (browse) => browse.callId === workspace.browserId,
  )?.environmentId;
  const selectOwnedBrowser = useEffectEvent(() => {
    if (workspace.activePanel === "browser" && workspace.environment === null)
      workspace.openEnvironment("browser");
  });
  useEffect(() => {
    if (!browserActive || conversationId === null) return;
    let current = true;
    void refresh().then((result) => {
      if (result === null) return;
      const owned = result.data?.items.find((item) => item.kind === "browser");
      if (
        current &&
        !result.error &&
        owned !== undefined &&
        owned.id !== null &&
        owned.id === activityEnvironmentId &&
        (owned.state === "ready" || owned.state === "starting")
      )
        selectOwnedBrowser();
    });
    return () => {
      current = false;
    };
  }, [
    browserActive,
    conversationId,
    agentId,
    target,
    workspace.browserId,
    activityEnvironmentId,
    refresh,
  ]);

  const desktopActivity = browses.findLast(
    (browse) => browse.environmentId && !browse.navigable && !browse.nativeId && isRunning(browse),
  );
  const desktopEnvironmentId = desktopActivity?.environmentId;
  const desktopCallId = desktopActivity?.callId;
  const openedDesktop = useRef(new Set<string>());
  const showDesktop = useEffectEvent(() => {
    if (workspace.activePanel === null && !useSourcesPanelStore.getState().isOpen)
      workspace.openEnvironment("desktop");
  });
  useEffect(() => {
    if (
      conversationId === null ||
      !panels.includes("desktop") ||
      !desktopEnvironmentId ||
      openedDesktop.current.has(desktopEnvironmentId)
    )
      return;
    let current = true;
    void refresh().then((result) => {
      const owned = result?.data?.items.find((item) => item.kind === "desktop");
      if (
        current &&
        result &&
        !result.error &&
        owned?.id === desktopEnvironmentId &&
        (owned.state === "ready" || owned.state === "starting")
      ) {
        openedDesktop.current.add(desktopEnvironmentId);
        showDesktop();
      }
    });
    return () => {
      current = false;
    };
  }, [conversationId, agentId, target, panels, desktopEnvironmentId, desktopCallId, refresh]);

  async function open(kind: WorkspaceEnvironment) {
    setFailed(false);
    workspace.openEnvironment(kind, trigger.current);
    try {
      if ((await prepareConversation()) === null) setFailed(true);
    } catch {
      setFailed(true);
    }
  }

  async function openWorkspace() {
    if (conversationId === null) {
      const first = panels[0];
      if (!first) {
        workspace.openPanel("files", trigger.current);
        return;
      }
      await open(first);
      return;
    }
    const last = workspace.activePanel ?? workspace.lastPanel;
    if (
      last === "files" ||
      (last === "visuals" && workspace.selection !== null) ||
      ((last === "browser" || last === "desktop") &&
        (panels.includes(last) || (last === "browser" && workspace.browserId !== null)))
    ) {
      workspace.openPanel(last, trigger.current);
      return;
    }
    if (workspace.browserId !== null) {
      workspace.openPanel("browser", trigger.current);
      return;
    }
    setOpening(true);
    setFailed(false);
    try {
      const result = await refresh();
      if (result === null) return; // The query's actor/organization/selection fence changed.
      if (result.error) throw result.error;
      const ready = result.data?.items.find(
        (item) =>
          panels.includes(item.kind) && (item.state === "ready" || item.state === "starting"),
      );
      if (ready) workspace.openEnvironment(ready.kind, trigger.current);
      else workspace.openPanel("files", trigger.current);
    } catch {
      setFailed(true);
      const fallback = panels[0];
      if (fallback) workspace.openEnvironment(fallback, trigger.current);
      else workspace.openPanel("files", trigger.current);
    } finally {
      setOpening(false);
    }
  }

  return (
    <>
      {buttonSlot &&
        createPortal(
          <span data-tour="chat-environments" className="inline-flex">
            <Button
              ref={trigger}
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("open")}
              title={t("open")}
              data-tour="chat-workspace-open"
              className="touch:size-11 size-8 shrink-0"
              disabled={preparing || opening}
              loading={preparing || opening}
              aria-busy={preparing || opening}
              onClick={() => void openWorkspace()}
            >
              <FolderOpen className="size-4" aria-hidden />
            </Button>
          </span>,
          buttonSlot,
        )}
      {panels.map((kind) => {
        const environment = environments.items?.find((item) => item.kind === kind);
        const active = visible && selected === kind;
        return (
          <ChatWorkspaceFrame key={kind} panel={kind} environment>
            {() =>
              failed || environments.error ? (
                <div role="alert" className="space-y-3 p-4 text-sm">
                  <p>{status("loadFailed")}</p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setFailed(false);
                      if (conversationId === null) void open(kind);
                      else void environments.refresh();
                    }}
                  >
                    {common("retry")}
                  </Button>
                </div>
              ) : environment && conversationId !== null ? (
                <ConversationEnvironmentView
                  conversationId={conversationId}
                  environment={environment}
                  visible={active}
                  onState={environments.remember}
                  onStart={async () => {
                    return await environments.start({
                      conversation: conversationId,
                      agent: agentId,
                      kind,
                    });
                  }}
                  onEnd={() =>
                    environments.end({ conversation: conversationId, agent: agentId, kind })
                  }
                  onRefresh={async () => {
                    const result = await environments.refresh();
                    if (result?.error) throw result.error;
                  }}
                  isStarting={environments.isStarting}
                  isEnding={environments.isEnding}
                />
              ) : (
                <div role="status" className="text-muted-foreground p-4 text-sm">
                  {status("loading")}
                </div>
              )
            }
          </ChatWorkspaceFrame>
        );
      })}
    </>
  );
}
