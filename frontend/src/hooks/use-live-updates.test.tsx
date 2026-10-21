import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveUpdates } from "./use-live-updates";
import { onRemoteChange, staleQueries } from "@/lib/live-updates";
import { COALESCE_MS } from "@/lib/coalesced-invalidation";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useLiveFeedStore, useOrgStore } from "@/stores";
import type { ChangeEvent } from "@/types/change-events";

interface SocketOptions {
  url: string;
  identity?: string;
  protocols: () => string[] | undefined;
  onMessage: (message: MessageEvent) => void;
  onOpen: () => void;
  onClose: () => void;
}

const socket = vi.hoisted(() => ({
  options: null as SocketOptions | null,
  connect: vi.fn(),
  disconnect: vi.fn(),
}));

vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: (options: SocketOptions) => {
    socket.options = options;
    return { connect: socket.connect, disconnect: socket.disconnect };
  },
}));
vi.mock("@/components/public-config/public-config-provider", () => ({
  usePublicConfig: () => ({ wsUrl: "wss://api.example.com" }),
}));

const EVENT: ChangeEvent = {
  organization_id: "org-1",
  resource: "agent",
  id: "agent-1",
  action: "updated",
  surface: "api_key",
  actor_user_id: "user-1",
  actor_name: "Ada",
  origin_tab: null,
};

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  client = new QueryClient();
  socket.options = null;
  socket.connect.mockReset();
  socket.disconnect.mockReset();
  useOrgStore.setState({ activeOrgId: "org-1" });
  useAuthStore.setState({ accessToken: "jwt", user: null });
});

describe("useLiveUpdates", () => {
  it("opens the organization's event socket with the token as a subprotocol", () => {
    const { unmount } = renderHook(() => useLiveUpdates(), { wrapper });

    expect(socket.options?.url).toBe(
      "wss://api.example.com/api/v1/ws/events?organization_id=org-1",
    );
    expect(socket.options?.protocols()).toEqual(["access_token.jwt", "events"]);
    expect(socket.options?.identity).toBeUndefined();
    expect(socket.connect).toHaveBeenCalled();

    unmount();
    expect(socket.disconnect).toHaveBeenCalled();
  });

  it("speaks for the signed-in person, so another one gets another socket", () => {
    useAuthStore.setState({ user: { id: "u1" } as never });

    renderHook(() => useLiveUpdates(), { wrapper });

    expect(socket.options?.identity).toBe("u1");
  });

  it("stays closed without an organization or a token", () => {
    useOrgStore.setState({ activeOrgId: null });
    renderHook(() => useLiveUpdates(), { wrapper });
    useOrgStore.setState({ activeOrgId: "org-1" });
    useAuthStore.setState({ accessToken: null });
    renderHook(() => useLiveUpdates(), { wrapper });

    expect(socket.connect).not.toHaveBeenCalled();
    expect(socket.options?.protocols()).toBeUndefined();
  });

  it("marks what the change made stale and tells whoever is listening", () => {
    vi.useFakeTimers();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const heard = vi.fn();
    const stop = onRemoteChange(heard);
    renderHook(() => useLiveUpdates(), { wrapper });

    socket.options?.onMessage(new MessageEvent("message", { data: JSON.stringify(EVENT) }));
    stop();

    // Told at once; marked stale with whatever else arrives in the same window.
    expect(heard).toHaveBeenCalledWith(EVENT);
    vi.advanceTimersByTime(COALESCE_MS);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.all() });
    vi.useRealTimers();
  });

  it("marks one change heard twice stale once", () => {
    vi.useFakeTimers();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderHook(() => useLiveUpdates(), { wrapper });

    socket.options?.onMessage(new MessageEvent("message", { data: JSON.stringify(EVENT) }));
    socket.options?.onMessage(new MessageEvent("message", { data: JSON.stringify(EVENT) }));
    vi.advanceTimersByTime(COALESCE_MS);

    // Each key the change stales, once - not once per time it was heard.
    expect(invalidate).toHaveBeenCalledTimes(new Set(staleQueries(EVENT).map(String)).size);
    vi.useRealTimers();
  });
});

describe("whether the feed is live", () => {
  it("follows the socket opening and closing, and is down once the hook goes", () => {
    const { unmount } = renderHook(() => useLiveUpdates(), { wrapper });

    socket.options?.onOpen();
    expect(useLiveFeedStore.getState().connected).toBe(true);
    socket.options?.onClose();
    expect(useLiveFeedStore.getState().connected).toBe(false);
    socket.options?.onOpen();
    unmount();
    expect(useLiveFeedStore.getState().connected).toBe(false);
  });
});

describe("coming back after a drop", () => {
  it("marks every cached answer stale, since the changes meanwhile were missed", () => {
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { unmount } = renderHook(() => useLiveUpdates(), { wrapper });

    socket.options?.onOpen();
    expect(invalidate).not.toHaveBeenCalled();
    socket.options?.onClose();
    socket.options?.onOpen();

    expect(invalidate).toHaveBeenCalledWith();
    unmount();
  });

  it("marks the cache stale on returning to an organization the tab visited before", () => {
    // Codex on #2248: A, then B, then A again - A's feed was closed while B's was
    // open, and its half-hour answers would have been shown as they were.
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { rerender, unmount } = renderHook(() => useLiveUpdates(), { wrapper });
    socket.options?.onOpen();
    useOrgStore.setState({ activeOrgId: "org-2" });
    rerender();
    socket.options?.onOpen();
    expect(invalidate).not.toHaveBeenCalled();

    useOrgStore.setState({ activeOrgId: "org-1" });
    rerender();
    socket.options?.onOpen();

    expect(invalidate).toHaveBeenCalledWith();
    unmount();
  });

  it("leaves another organization's first open alone - its queries are new keys", () => {
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { rerender, unmount } = renderHook(() => useLiveUpdates(), { wrapper });
    socket.options?.onOpen();

    useOrgStore.setState({ activeOrgId: "org-2" });
    rerender();
    socket.options?.onOpen();

    expect(invalidate).not.toHaveBeenCalled();
    unmount();
  });
});
