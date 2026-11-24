"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { useWebSocket } from "@/hooks/use-websocket";
import {
  applyBrowserFrame,
  protectBrowse,
  type Browse,
  type BrowserProtection,
} from "@/lib/browse";
import { useAuthStore } from "@/stores";
import { useOrgStore } from "@/stores/org-store";
import type { BrowserFrame } from "@/types/chat";

/** Commands for an unprotected live browser; protected pages accept no generic control. */
export type BrowserCommand =
  | { type: "take_over" }
  | { type: "navigate"; url: string }
  | { type: "back" | "forward" | "reload" }
  | { type: "give_back"; remember?: boolean }
  | { type: "click"; x: number; y: number }
  | { type: "type"; text: string }
  | { type: "key"; key: string }
  | { type: "scroll"; dy: number }
  | { type: "resize"; width: number; height: number; scale: 1 | 2 };

export type LiveBrowseStatus = "connecting" | "live" | "gone" | "forbidden" | "unavailable";

interface Snapshot {
  type: "browser_snapshot";
  task: string;
  can_control: boolean;
  can_remember?: boolean;
  trace: BrowserFrame[];
  frame: BrowserFrame | null;
}
interface LiveState {
  generation: object;
  browses: Browse[];
  task: string;
  canControl: boolean;
  canRemember: boolean;
  status: LiveBrowseStatus;
}
const CLOSED: Record<number, LiveBrowseStatus> = {
  4404: "gone",
  4403: "forbidden",
  1011: "unavailable",
};
const protectedEvent = (frame: BrowserFrame) =>
  frame.kind === "browser_protected" || frame.output_protected === true;

/**
 * An addressed, authorized live view may reconstruct a protected reconnect
 * snapshot without an opening event. The general chat reducer still drops
 * unknown late calls. Protection also clears its retained parent chat cache.
 */
export function useLiveBrowse(
  runId: string,
  callId: string,
  enabled = true,
  onProtected?: (protection: BrowserProtection) => void,
) {
  const { wsUrl } = usePublicConfig();
  const accessToken = useAuthStore((state) => state.accessToken);
  const principal = useAuthStore((state) => state.user?.id);
  const organization = useOrgStore((state) => state.activeOrgId);
  const authenticated = !!accessToken;
  const scope = JSON.stringify([principal ?? null, organization, runId, callId]);
  // A -> B -> A still creates a new connection generation; an old callback
  // cannot become current merely because its scope string matches again.
  const generation = useMemo(
    () => ({ scope, enabled, authenticated }),
    [scope, enabled, authenticated],
  );
  const committed = useRef<object | null>(null);
  const protectedGeneration = useRef<object | null>(null);
  const [state, setState] = useState<LiveState | null>(null);
  useLayoutEffect(() => {
    committed.current = generation;
    return () => {
      if (committed.current === generation) committed.current = null;
    };
  }, [generation]);
  const isCurrent = useCallback(
    () =>
      enabled &&
      !!principal &&
      committed.current === generation &&
      !!useAuthStore.getState().accessToken &&
      useAuthStore.getState().user?.id === principal &&
      useOrgStore.getState().activeOrgId === organization,
    [enabled, generation, principal, organization],
  );

  const url = useMemo(
    () => `${wsUrl}/api/v1/ws/browse/${encodeURIComponent(runId)}/${encodeURIComponent(callId)}`,
    [wsUrl, runId, callId],
  );
  const protocols = useCallback(() => {
    if (!isCurrent()) return undefined;
    const token = useAuthStore.getState().accessToken;
    return token ? [`access_token.${token}`, "browse"] : undefined;
  }, [isCurrent]);

  const onMessage = useCallback(
    (message: MessageEvent) => {
      if (!isCurrent()) return;
      const data = JSON.parse(String(message.data)) as Snapshot | BrowserFrame;
      const snapshot = "type" in data && data.type === "browser_snapshot" ? data : null;
      const frames = (
        snapshot
          ? [...snapshot.trace, ...(snapshot.frame ? [snapshot.frame] : [])]
          : [data as BrowserFrame]
      )
        .filter((frame) => frame.call_id === callId && (!frame.run_id || frame.run_id === runId))
        .map((frame) => ({ ...frame, run_id: runId }));
      const protection = frames.find(protectedEvent);
      if (protection) {
        // Set before React renders so an older send callback is fenced immediately.
        protectedGeneration.current = generation;
        onProtected?.({ callId, runId, tabId: protection.tab_id ?? null });
      }
      const alreadyProtected = protectedGeneration.current === generation;
      setState((before) => {
        const current = before?.generation === generation ? before : null;
        let next = snapshot
          ? (current?.browses.filter((browse) => browse.outputProtected) ?? [])
          : (current?.browses ?? []);
        for (const frame of frames) {
          if (!next.length && protectedEvent(frame)) {
            next = applyBrowserFrame([], {
              ...frame,
              kind: "browser_opened",
              output_protected: true,
            });
          }
          next = applyBrowserFrame(next, frame);
        }
        const protectedOutput = alreadyProtected || next.some((browse) => browse.outputProtected);
        if (protectedOutput) next = next.map(protectBrowse);
        return {
          generation,
          browses: next,
          task: protectedOutput ? "" : (snapshot?.task ?? current?.task ?? ""),
          canControl: !protectedOutput && (snapshot?.can_control ?? current?.canControl ?? false),
          canRemember:
            !protectedOutput && (snapshot?.can_remember ?? current?.canRemember ?? false),
          status: snapshot ? "live" : (current?.status ?? "connecting"),
        };
      });
    },
    [isCurrent, callId, runId, generation, onProtected],
  );

  const onClose = useCallback(
    (event: CloseEvent) => {
      if (!isCurrent()) return;
      const closed = CLOSED[event.code];
      setState((before) => ({
        generation,
        // A reconnect may recover the page, but must obtain a fresh held event
        // before offering teaching Start/Resume with a server-issued lease.
        browses:
          before?.generation === generation
            ? before.browses.map((browse) => ({ ...browse, takeoverId: null }))
            : [],
        task: before?.generation === generation ? before.task : "",
        canControl: false,
        canRemember: false,
        status: closed ?? "connecting",
      }));
    },
    [isCurrent, generation],
  );

  // A no-store plan receipt is another authoritative protection signal.
  // It clears this view and the parent cache without sending a browser command.
  const protect = useCallback(() => {
    if (!isCurrent() || protectedGeneration.current === generation) return;
    protectedGeneration.current = generation;
    onProtected?.({ callId, runId });
    setState((before) =>
      before?.generation === generation
        ? {
            ...before,
            browses: before.browses.map(protectBrowse),
            task: "",
            canControl: false,
            canRemember: false,
          }
        : before,
    );
  }, [isCurrent, generation, onProtected, callId, runId]);

  const { connect, disconnect, sendMessage } = useWebSocket({
    url,
    protocols,
    identity: scope,
    onMessage,
    onClose,
  });
  const current = authenticated && principal && state?.generation === generation ? state : null;
  const browse = current?.browses.find((entry) => entry.callId === callId) ?? null;
  const finished = browse?.outcome != null;
  useEffect(() => {
    // Completed views fetch one cached snapshot, then release only their socket.
    if (!accessToken || !principal || !enabled || finished) return;
    connect();
    return () => disconnect();
  }, [accessToken, principal, enabled, finished, connect, disconnect]);
  const send = useCallback(
    (command: BrowserCommand) => {
      if (isCurrent() && protectedGeneration.current !== generation) sendMessage(command);
    },
    [isCurrent, generation, sendMessage],
  );
  return {
    browse,
    task: current?.task ?? "",
    canControl: current?.canControl ?? false,
    canRemember: current?.canRemember ?? false,
    status: current?.status ?? "connecting",
    send,
    protect,
  };
}
