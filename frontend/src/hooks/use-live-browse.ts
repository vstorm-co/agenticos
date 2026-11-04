"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { useWebSocket } from "@/hooks/use-websocket";
import { applyBrowserFrame, type Browse } from "@/lib/browse";
import { useAuthStore } from "@/stores";
import type { BrowserFrame } from "@/types/chat";

/** What a person watching a browse may ask of it (#2128) - `BrowserCommand` on the server. */
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

/** Where the live view stands: still connecting, live, or refused and why. */
export type LiveBrowseStatus = "connecting" | "live" | "gone" | "forbidden" | "unavailable";

interface Snapshot {
  type: "browser_snapshot";
  task: string;
  can_control: boolean;
  /** Whether this viewer may keep the sign-in they make here - their own browse (#2129). */
  can_remember?: boolean;
  trace: BrowserFrame[];
  frame: BrowserFrame | null;
}

/** The close codes the live view answers with, and what each means to a viewer. */
const CLOSED: Record<number, LiveBrowseStatus> = {
  4404: "gone",
  4403: "forbidden",
  1011: "unavailable",
};

/**
 * One browse's live view: what it has done, its page as it is now, and a way to drive it.
 *
 * The socket's first message is a snapshot - the task, the trace so far and the
 * latest picture - so a person opening a link mid-browse sees where it is rather
 * than an empty frame until the next step; every frame after that is folded in
 * with the reducer the chat uses, so the two surfaces cannot disagree about a
 * browse. `enabled` false holds the socket closed.
 */
export function useLiveBrowse(runId: string, callId: string, enabled = true) {
  const { wsUrl } = usePublicConfig();
  const accessToken = useAuthStore((state) => state.accessToken);
  const principal = useAuthStore((state) => state.user?.id);
  const scope = `${principal ?? ""}:${runId}:${callId}`;
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [browses, setBrowses] = useState<Browse[]>([]);
  const [task, setTask] = useState("");
  const [canControl, setCanControl] = useState(false);
  const [canRemember, setCanRemember] = useState(false);
  const [status, setStatus] = useState<LiveBrowseStatus>("connecting");

  const url = useMemo(
    () => `${wsUrl}/api/v1/ws/browse/${encodeURIComponent(runId)}/${encodeURIComponent(callId)}`,
    [wsUrl, runId, callId],
  );
  const protocols = useCallback(() => {
    const token = useAuthStore.getState().accessToken;
    return token ? [`access_token.${token}`, "browse"] : undefined;
  }, []);

  const onMessage = useCallback(
    (message: MessageEvent) => {
      setLoadedFor(scope);
      const data = JSON.parse(String(message.data)) as Snapshot | BrowserFrame;
      if ("type" in data && data.type === "browser_snapshot") {
        let next: Browse[] = [];
        for (const frame of data.trace) next = applyBrowserFrame(next, frame);
        if (data.frame) next = applyBrowserFrame(next, data.frame);
        setBrowses(next);
        setTask(data.task);
        setCanControl(data.can_control);
        setCanRemember(data.can_remember === true);
        setStatus("live");
        return;
      }
      setBrowses((current) => applyBrowserFrame(current, data as BrowserFrame));
    },
    [scope],
  );

  const onClose = useCallback((event: CloseEvent) => {
    const closed = CLOSED[event.code];
    if (closed) setStatus(closed);
  }, []);

  const { connect, disconnect, sendMessage } = useWebSocket({
    url,
    protocols,
    identity: principal,
    onMessage,
    onClose,
  });

  const browse =
    loadedFor === scope ? (browses.find((entry) => entry.callId === callId) ?? null) : null;
  const finished = browse?.outcome != null;

  useEffect(() => {
    // Completed views fetch one cached snapshot, then release their socket.
    if (!accessToken || !enabled || finished) return;
    connect();
    return () => disconnect();
  }, [accessToken, enabled, finished, connect, disconnect]);

  const send = useCallback((command: BrowserCommand) => sendMessage(command), [sendMessage]);

  return { browse, task, canControl, canRemember, status, send };
}
