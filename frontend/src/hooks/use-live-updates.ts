"use client";

import { useCallback, useEffect, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { useWebSocket } from "@/hooks/use-websocket";
import { announceChange, staleQueries } from "@/lib/live-updates";
import { useAuthStore, useOrgStore } from "@/stores";
import type { ChangeEvent } from "@/types/change-events";

/**
 * Keep the console's cached answers current with changes made elsewhere (#2061).
 *
 * One socket per tab, to `/ws/events` for the active organization. Each event
 * the server lets through - it filters by what this member may read - marks the
 * matching queries stale, so a list or a detail with nothing local refetches in
 * place, and is announced to any page holding a draft of that row, which decides
 * for itself whether to adopt the new values or ask first.
 *
 * Opened again whenever the access token changes: a live socket is reused as it
 * is, and one the server refused at the handshake is retried with the new token.
 * While it is down the console behaves as it always did.
 */
export function useLiveUpdates(): void {
  const queryClient = useQueryClient();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const accessToken = useAuthStore((state) => state.accessToken);
  const { wsUrl: wsOrigin } = usePublicConfig();
  const url = useMemo(
    () => `${wsOrigin}/api/v1/ws/events?organization_id=${encodeURIComponent(activeOrgId ?? "")}`,
    [wsOrigin, activeOrgId],
  );
  const protocols = useCallback(() => {
    const token = useAuthStore.getState().accessToken;
    return token ? [`access_token.${token}`, "events"] : undefined;
  }, []);
  const onMessage = useCallback(
    (message: MessageEvent) => {
      const event = JSON.parse(String(message.data)) as ChangeEvent;
      for (const queryKey of staleQueries(event)) {
        void queryClient.invalidateQueries({ queryKey });
      }
      announceChange(event);
    },
    [queryClient],
  );
  const { connect, disconnect } = useWebSocket({ url, protocols, onMessage });

  useEffect(() => {
    if (!activeOrgId || !accessToken) return;
    connect();
    return () => disconnect();
  }, [activeOrgId, accessToken, connect, disconnect]);
}
