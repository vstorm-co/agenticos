"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import type { Browse, BrowserProtection } from "@/lib/browse";
import { workspaceStartReason, type WorkspaceStartAccess } from "@/lib/workspace-panels";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useChatControlsStore, chatControlScope } from "@/stores/chat-controls-store";
import { useBrowserPanelStore, type BrowseSurface } from "@/stores/browser-panel-store";
import type { ChatMessageFile } from "@/types";
import type { PageComment } from "./browser-comment";
import { BrowserPanel } from "./browser-panel";
import { WorkspaceFiles } from "./workspace-files";
import { WorkspaceRail } from "./workspace-rail";
import { ChatAgentSettingsPanel } from "./agent-settings-panel";
import { WorkspaceTasksPanel } from "./workspace-tasks-panel";

interface WorkspacePanelsProps {
  teamRoom: boolean;
  compact: boolean;
  agentId: string | null;
  hostedCapabilities: readonly string[] | null;
  canRun: boolean;
  agentUsesLocalTools: boolean;
  conversationId: string | null;
  browses: Browse[];
  onBrowserProtected?: (protection: BrowserProtection) => void;
  surfaces: ReadonlyMap<string, BrowseSurface>;
  revision: number;
  attachments: ChatMessageFile[];
  busy: boolean;
  connected: boolean;
  readOnly: boolean;
  loading: boolean;
  onSend: (message: string) => void;
  onComment: (comment: PageComment) => void;
}

/** User-opened surfaces; starting one is an explicit, ordinary chat turn. */
export function WorkspacePanels(props: WorkspacePanelsProps) {
  const t = useTranslations("chat.workspace");
  const chat = useTranslations("chat");
  const account = useAuthStore((state) => state.user?.id);
  const organization = useOrgStore((state) => state.activeOrgId);
  // Subscribe to saved defaults: Work on's fallback getters do not subscribe themselves.
  useChatControlsStore((state) => state.byScope[chatControlScope(account, organization)]);
  const surface = useBrowserPanelStore((state) => state.surface);
  const open = useBrowserPanelStore((state) => state.openSurface);
  const close = useBrowserPanelStore((state) => state.close);
  // Room responders are selected independently of the personal-chat agent.
  const settingsAgentId = props.teamRoom ? null : props.agentId;
  const [filesSlot, setFilesSlot] = useState<HTMLSpanElement | null>(null);
  const panelPrefix = useId();
  const panelIds = {
    browser: `${panelPrefix}-browser`,
    computer: `${panelPrefix}-computer`,
    settings: `${panelPrefix}-settings`,
    tasks: `${panelPrefix}-tasks`,
  };
  const localSelected = useWorkOnStore((state) =>
    Boolean(
      state.targetFor(props.conversationId) ||
      state.browserFor(props.conversationId) ||
      state.computerFor(props.conversationId) ||
      state.codingFor(props.conversationId) ||
      state.skillsFor(props.conversationId).length,
    ),
  );
  const previous = useRef({
    account,
    organization,
    agent: props.agentId,
    conversation: props.conversationId,
  });
  useLayoutEffect(() => {
    const before = previous.current;
    previous.current = {
      account,
      organization,
      agent: props.agentId,
      conversation: props.conversationId,
    };
    const adopted = before.conversation === null && props.busy && !props.loading;
    if (
      before.account !== account ||
      before.organization !== organization ||
      before.agent !== props.agentId ||
      (before.conversation !== props.conversationId && !adopted) ||
      (surface === "settings" && settingsAgentId === null)
    )
      close();
  }, [
    account,
    organization,
    props.agentId,
    props.conversationId,
    props.busy,
    props.loading,
    surface,
    settingsAgentId,
    close,
  ]);
  const access: WorkspaceStartAccess = {
    teamRoom: props.teamRoom,
    hasAgent: props.agentId !== null,
    hostedCapabilities: props.hostedCapabilities,
    canRun: props.canRun,
    readOnly: props.readOnly || props.loading,
    localSelected: localSelected || props.agentUsesLocalTools,
    busy: props.busy,
    connected: props.connected,
  };
  const start = (kind: BrowseSurface, url?: string) => {
    if (workspaceStartReason(access, kind) !== null) return;
    // A fresh request deliberately leaves a historical visit and follows the next real view.
    open(kind);
    if (kind === "computer") props.onSend(t("computerPrompt"));
    else if (url) props.onSend(t("browserPrompt", { url }));
  };
  return (
    <>
      <BrowserPanel
        panelId={surface === "computer" ? panelIds.computer : panelIds.browser}
        browses={props.loading ? [] : props.browses}
        onProtected={props.onBrowserProtected}
        surfaces={props.surfaces}
        access={access}
        onStart={start}
        onComment={props.onComment}
        onResume={
          workspaceStartReason(access, "browser") === null
            ? () => props.onSend(chat("browserResumePrompt"))
            : undefined
        }
      />
      {surface !== "browser" && <div id={panelIds.browser} hidden aria-hidden="true" />}
      {surface !== "computer" && <div id={panelIds.computer} hidden aria-hidden="true" />}
      {surface === "tasks" ? (
        <WorkspaceTasksPanel
          key={`${account}:${organization}:${props.agentId}:${props.conversationId}`}
          panelId={panelIds.tasks}
          conversationId={props.conversationId}
          readOnly={props.readOnly || props.loading}
          onClose={close}
        />
      ) : (
        <div id={panelIds.tasks} hidden aria-hidden="true" />
      )}
      {settingsAgentId !== null && surface !== "settings" && (
        <div id={panelIds.settings} hidden aria-hidden="true" />
      )}
      <WorkspaceFiles
        key={`${account}:${organization}:${props.agentId}:${props.conversationId}`}
        conversationId={props.conversationId}
        revision={props.revision}
        attachments={props.attachments}
        buttonSlot={filesSlot}
        open={surface === "files"}
        onOpenChange={(shown) => (shown ? open("files") : close())}
        responsive
      />
      {settingsAgentId !== null && (
        <ChatAgentSettingsPanel
          key={`${account}:${organization}:${settingsAgentId}`}
          panelId={panelIds.settings}
          agentId={settingsAgentId}
          open={surface === "settings"}
          readOnly={props.readOnly || props.loading}
          onClose={close}
        />
      )}
      {!props.compact && (
        <WorkspaceRail
          filesSlot={setFilesSlot}
          hasAgent={settingsAgentId !== null}
          panelIds={panelIds}
        />
      )}
    </>
  );
}
