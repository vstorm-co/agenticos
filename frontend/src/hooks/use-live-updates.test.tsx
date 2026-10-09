import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useLiveUpdates } from "./use-live-updates";
import { onRemoteChange } from "@/lib/live-updates";
import { qk } from "@/lib/query-keys";
import { useAuthStore, useOrgStore } from "@/stores";
import type { ChangeEvent } from "@/types/change-events";

interface SocketOptions {
  url: string;
  protocols: () => string[] | undefined;
  onMessage: (message: MessageEvent) => void;
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
  useAuthStore.setState({ accessToken: "jwt" });
});

describe("useLiveUpdates", () => {
  it("opens the organization's event socket with the token as a subprotocol", () => {
    const { unmount } = renderHook(() => useLiveUpdates(), { wrapper });

    expect(socket.options?.url).toBe(
      "wss://api.example.com/api/v1/ws/events?organization_id=org-1",
    );
    expect(socket.options?.protocols()).toEqual(["access_token.jwt", "events"]);
    expect(socket.connect).toHaveBeenCalled();

    unmount();
    expect(socket.disconnect).toHaveBeenCalled();
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
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const heard = vi.fn();
    const stop = onRemoteChange(heard);
    renderHook(() => useLiveUpdates(), { wrapper });

    socket.options?.onMessage(new MessageEvent("message", { data: JSON.stringify(EVENT) }));
    stop();

    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.all() });
    expect(heard).toHaveBeenCalledWith(EVENT);
  });
});
