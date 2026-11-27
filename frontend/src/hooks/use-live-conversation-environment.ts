"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { useWebSocket } from "@/hooks/use-websocket";
import type { BrowserCommand } from "@/hooks/use-live-browse";
import { applyBrowserFrame, type Browse } from "@/lib/browse";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { parseEnvironmentEvent } from "@/lib/environment-stream";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";

type Status = "connecting" | "live" | "gone" | "forbidden" | "unavailable" | "malformed";
interface Snapshot {
  scope: string;
  status: Status;
  environment: ConversationEnvironment | null;
  browses: Browse[];
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
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const invalidScope = useRef<string | null>(null);
  const current = snapshot?.scope === scope && environment.state === "ready" ? snapshot : null;
  const url = useMemo(
    () =>
      `${wsUrl}/api/v1/ws/conversations/${encodeURIComponent(conversationId)}/environments/${encodeURIComponent(environment.id ?? "")}?project_execution_target=${environment.execution_target}`,
    [wsUrl, conversationId, environment.id, environment.execution_target],
  );
  const protocols = useCallback(() => {
    const currentToken = useAuthStore.getState().accessToken;
    return currentToken ? [`access_token.${currentToken}`, "environment"] : undefined;
  }, []);
  const onMessage = useCallback(
    (message: MessageEvent) => {
      if (invalidScope.current === scope) return;
      let payload: unknown;
      try {
        payload = JSON.parse(String(message.data));
      } catch {
        invalidScope.current = scope;
        setSnapshot({ scope, status: "malformed", environment: null, browses: [] });
        return;
      }
      const parsed = parseEnvironmentEvent(payload, environment);
      if (parsed === null) {
        invalidScope.current = scope;
        setSnapshot({ scope, status: "malformed", environment: null, browses: [] });
        return;
      }
      setSnapshot((previous) => {
        const same = previous?.scope === scope ? previous : null;
        const next =
          parsed.type === "environment_state" ? parsed.data : (same?.environment ?? null);
        const state = next?.state;
        return {
          scope,
          status:
            state === "expired"
              ? "gone"
              : state === "failed"
                ? "unavailable"
                : state === "ready"
                  ? "live"
                  : "connecting",
          environment: next,
          browses:
            state !== "ready"
              ? []
              : parsed.type === "browser_event"
                ? applyBrowserFrame(same?.browses ?? [], parsed.data)
                : (same?.browses ?? []),
        };
      });
    },
    [scope, environment],
  );
  const onClose = useCallback(
    (event: CloseEvent) => {
      const status: Status =
        invalidScope.current === scope
          ? "malformed"
          : event.code === 4403 || event.code === 4401
            ? "forbidden"
            : event.code === 4404
              ? "gone"
              : "unavailable";
      setSnapshot((previous) => ({
        scope,
        status,
        environment: previous?.scope === scope ? previous.environment : null,
        browses: [],
      }));
    },
    [scope],
  );
  const { connect, disconnect, sendMessage } = useWebSocket({
    url,
    protocols,
    identity: scope,
    messageScope: scope,
    onMessage,
    onClose,
  });
  const malformed = current?.status === "malformed";
  const terminal = malformed || current?.status === "gone" || current?.status === "forbidden";
  const state = current?.environment?.state ?? environment.state;
  useEffect(() => {
    if (!authenticated || !enabled || environment.id === null || state !== "ready" || terminal)
      return;
    connect();
    return () => disconnect();
  }, [authenticated, enabled, environment.id, state, terminal, connect, disconnect]);
  const status = current?.status ?? "connecting";
  const canControl = current?.environment?.can_control === true;
  const control = current?.environment?.control;
  const ready = current?.environment?.state === "ready";
  const send = useCallback(
    (command: BrowserCommand) => {
      if (
        authenticated &&
        enabled &&
        status === "live" &&
        ready &&
        canControl &&
        (command.type === "take_over" ? control !== "agent" : control === "human")
      )
        sendMessage(command);
    },
    [authenticated, enabled, status, ready, canControl, control, sendMessage],
  );
  const retry = useCallback(() => {
    if (!authenticated || !enabled || environment.id === null || environment.state !== "ready")
      return;
    invalidScope.current = null;
    setSnapshot(null);
    connect();
  }, [authenticated, enabled, environment.id, environment.state, connect]);

  return {
    status,
    environment: current?.environment,
    browse: current?.browses.find((browse) => browse.callId === environment.id) ?? null,
    send,
    retry,
  };
}
