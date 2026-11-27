"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { useWebSocket } from "@/hooks/use-websocket";
import type { BrowserCommand } from "@/hooks/use-live-browse";
import { applyBrowserFrame, type Browse } from "@/lib/browse";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { parseEnvironmentEvent, type EnvironmentTabs } from "@/lib/environment-stream";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

type Status = "connecting" | "live" | "gone" | "forbidden" | "unavailable" | "malformed";
interface Snapshot {
  scope: string;
  epoch: number;
  status: Status;
  environment: ConversationEnvironment | null;
  browses: Browse[];
  tabs: EnvironmentTabs | null;
}

/** Disconnecting a view releases its socket, never its remote browser or desktop. */
export function useLiveConversationEnvironment(
  conversationId: string,
  environment: ConversationEnvironment,
  enabled: boolean,
) {
  const { wsUrl } = usePublicConfig();
  const token = useAuthStore((state) => state.accessToken);
  const authenticated = Boolean(token);
  const actor = useAuthStore((state) => state.user?.id ?? null);
  const owner = useAuthStore((state) => state.sessionOwnerId ?? actor);
  const org = useOrgStore((state) => state.activeOrgId);
  const scope = JSON.stringify([
    owner,
    actor,
    org,
    conversationId,
    environment.agent_id,
    environment.id,
    environment.execution_target,
  ]);
  // A panel's next admission needs a fresh handshake even if the transport
  // would otherwise reuse its deferred-close socket after a quick hide/show.
  const active = authenticated && enabled;
  const [connection, setConnection] = useState({ scope, active, epoch: 0 });
  if (connection.scope !== scope || connection.active !== active) {
    setConnection({ scope, active, epoch: connection.epoch + 1 });
  }
  const epoch = connection.epoch;
  const socketScope = JSON.stringify([scope, epoch]);
  const currentSocket = useRef<string | null>(socketScope);
  // Fence buffered callbacks before passive socket effects replace the transport.
  useLayoutEffect(() => {
    currentSocket.current = socketScope;
    return () => {
      currentSocket.current = null;
    };
  }, [socketScope]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [pendingTab, setPendingTab] = useState<{ socket: string; id: string } | null>(null);
  const invalidScope = useRef<string | null>(null);
  const current = snapshot?.scope === scope && environment.state === "ready" ? snapshot : null;
  const fresh = current !== null && current.epoch === epoch;
  const url = useMemo(
    () =>
      `${wsUrl}/api/v1/ws/conversations/${encodeURIComponent(conversationId)}/environments/${encodeURIComponent(environment.id ?? "")}?project_execution_target=${environment.execution_target}`,
    [wsUrl, conversationId, environment.id, environment.execution_target],
  );
  const protocols = useCallback(() => {
    const currentToken = useAuthStore.getState().accessToken;
    return currentToken
      ? [`access_token.${currentToken}`, "environment", "environment.tabs.v1"]
      : undefined;
  }, []);
  const onMessage = useCallback(
    (message: MessageEvent) => {
      if (currentSocket.current !== socketScope || invalidScope.current === socketScope) return;
      let payload: unknown;
      try {
        payload = JSON.parse(String(message.data));
      } catch {
        invalidScope.current = socketScope;
        setSnapshot({
          scope,
          epoch,
          status: "malformed",
          environment: null,
          browses: [],
          tabs: null,
        });
        return;
      }
      const parsed = parseEnvironmentEvent(payload, environment);
      if (parsed === null) {
        invalidScope.current = socketScope;
        setSnapshot({
          scope,
          epoch,
          status: "malformed",
          environment: null,
          browses: [],
          tabs: null,
        });
        return;
      }
      const selectionError =
        parsed.type === "browser_event" &&
        parsed.data.kind === "browser_control_error" &&
        parsed.data.operation === "activate_tab";
      if (parsed.type === "environment_tabs") {
        setPendingTab((pending) =>
          pending?.socket === socketScope && pending.id === parsed.data.active_tab_id
            ? null
            : pending,
        );
      } else if (selectionError) {
        setPendingTab((pending) =>
          pending?.socket === socketScope && pending.id === parsed.data.tab_id ? null : pending,
        );
      }
      setSnapshot((previous) => {
        const same = previous?.scope === scope ? previous : null;
        if (
          parsed.type === "browser_event" &&
          parsed.data.kind === "browser_frame" &&
          same?.tabs &&
          parsed.data.tab_id !== same.tabs.active_tab_id
        )
          return previous;
        const next =
          parsed.type === "environment_state"
            ? parsed.data
            : same?.epoch === epoch
              ? same.environment
              : null;
        const state = next?.state;
        const browses = same?.browses ?? [];
        const released =
          same?.epoch !== epoch ||
          (parsed.type === "environment_state" && parsed.data.control !== "human");
        const observed = released
          ? browses.map((browse) => ({ ...browse, heldBy: null, heldById: null }))
          : browses;
        const selectedPage =
          parsed.type === "environment_tabs"
            ? parsed.data.tabs.find((tab) => tab.id === parsed.data.active_tab_id)
            : undefined;
        const switched =
          parsed.type === "environment_tabs" &&
          same?.tabs?.active_tab_id !== parsed.data.active_tab_id;
        const selectedBrowses =
          switched || selectionError
            ? observed.map((browse) => ({
                ...browse,
                image: null,
                pointer: null,
                tabId:
                  parsed.type === "environment_tabs" ? parsed.data.active_tab_id : browse.tabId,
                url: selectedPage?.url ?? null,
                title: selectedPage?.title ?? null,
              }))
            : observed;
        return {
          scope,
          epoch,
          status:
            state === "expired"
              ? "gone"
              : state === "failed"
                ? "unavailable"
                : state === "ready"
                  ? "live"
                  : "connecting",
          environment: next,
          tabs:
            state !== "ready"
              ? null
              : parsed.type === "environment_tabs"
                ? parsed.data
                : (same?.tabs ?? null),
          browses:
            state !== "ready"
              ? []
              : parsed.type === "browser_event"
                ? applyBrowserFrame(selectedBrowses, parsed.data)
                : selectedBrowses,
        };
      });
    },
    [scope, socketScope, epoch, environment],
  );
  const onClose = useCallback(
    (event: CloseEvent) => {
      if (currentSocket.current !== socketScope) return;
      setPendingTab((pending) => (pending?.socket === socketScope ? null : pending));
      const status: Status =
        invalidScope.current === socketScope
          ? "malformed"
          : event.code === 4403 || event.code === 4401
            ? "forbidden"
            : event.code === 4404
              ? "gone"
              : "unavailable";
      setSnapshot((previous) => ({
        scope,
        epoch,
        status,
        environment: previous?.scope === scope ? previous.environment : null,
        browses: [],
        tabs: null,
      }));
    },
    [scope, socketScope, epoch],
  );
  const { connect, disconnect, sendMessage } = useWebSocket({
    url,
    protocols,
    identity: socketScope,
    messageScope: socketScope,
    onMessage,
    onClose,
  });
  const malformed = fresh && current.status === "malformed";
  const terminal =
    malformed || (fresh && (current.status === "gone" || current.status === "forbidden"));
  const state = current?.environment?.state ?? environment.state;
  useEffect(() => {
    if (!authenticated || !enabled || environment.id === null || state !== "ready" || terminal)
      return;
    connect();
    return () => disconnect();
  }, [authenticated, enabled, environment.id, socketScope, state, terminal, connect, disconnect]);
  const status = fresh ? current.status : "connecting";
  const observed = current?.browses.find((browse) => browse.callId === environment.id) ?? null;
  // Keep observation pixels without carrying another socket's control grant.
  const selectingTab = pendingTab?.socket === socketScope;
  const browse =
    observed === null
      ? null
      : {
          ...observed,
          ...(!fresh ? { heldBy: null, heldById: null } : {}),
          ...(selectingTab ? { image: null, pointer: null } : {}),
        };
  const holding = actor !== null && browse?.heldById === actor;
  const canControl = actor !== null && current?.environment?.can_control === true;
  const control = current?.environment?.control;
  const ready = current?.environment?.state === "ready";
  const send = useCallback(
    (command: BrowserCommand) => {
      if (
        currentSocket.current === socketScope &&
        authenticated &&
        enabled &&
        status === "live" &&
        ready &&
        canControl &&
        (!selectingTab || command.type === "give_back") &&
        (command.type === "take_over"
          ? control !== "agent"
          : command.type === "resize"
            ? environment.kind === "browser" &&
              (control === "none" || (control === "human" && holding))
            : control === "human" && holding)
      )
        sendMessage(command);
    },
    [
      socketScope,
      authenticated,
      enabled,
      status,
      ready,
      canControl,
      selectingTab,
      control,
      holding,
      environment.kind,
      sendMessage,
    ],
  );
  const activateTab = useCallback(
    (tabId: string) => {
      if (
        currentSocket.current === socketScope &&
        authenticated &&
        enabled &&
        status === "live" &&
        ready &&
        canControl &&
        environment.kind === "browser" &&
        (control === "none" || (control === "human" && holding)) &&
        !selectingTab &&
        current?.tabs?.tabs.some((tab) => tab.id === tabId)
      ) {
        setPendingTab({ socket: socketScope, id: tabId });
        sendMessage({ type: "activate_tab", tab_id: tabId });
      }
    },
    [
      socketScope,
      authenticated,
      enabled,
      status,
      ready,
      canControl,
      environment.kind,
      control,
      holding,
      current?.tabs,
      selectingTab,
      sendMessage,
    ],
  );
  const retry = useCallback(() => {
    if (!authenticated || !enabled || environment.id === null || environment.state !== "ready")
      return;
    invalidScope.current = null;
    setSnapshot(null);
    setConnection((previous) => ({ ...previous, epoch: previous.epoch + 1 }));
  }, [authenticated, enabled, environment.id, environment.state, setConnection]);

  return {
    status,
    environment: current?.environment,
    browse,
    tabs: current?.tabs ?? null,
    activateTab,
    selectingTab,
    send,
    retry,
  };
}
