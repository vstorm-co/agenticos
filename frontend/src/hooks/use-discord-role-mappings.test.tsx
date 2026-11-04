import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDiscordRoleMappings, useDiscordServers } from "./use-discord-role-mappings";
import { apiClient, ApiError } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const MAPPING = {
  id: "m-1",
  channel_bot_id: "b-1",
  guild_id: "1100",
  guild_name: "Acme HQ",
  discord_role_id: "7",
  discord_role_name: "Finance",
  group_id: "g-1",
  group_name: "Finance",
  role: null,
  created_at: "2026-11-01T00:00:00Z",
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [MAPPING], total: 1 });
});

describe("useDiscordRoleMappings", () => {
  it("reads the bot's mappings", async () => {
    const { result } = renderHook(() => useDiscordRoleMappings("b-1"), { wrapper });

    await waitFor(() => expect(result.current.mappings).toEqual([MAPPING]));
    expect(apiClient.get).toHaveBeenCalledWith("/channels/bots/b-1/role-mappings");
  });

  it("maps a role, refetches the list and says so", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(MAPPING);
    const { result } = renderHook(() => useDiscordRoleMappings("b-1"), { wrapper });
    await waitFor(() => expect(result.current.mappings).toHaveLength(1));
    const input = { guild_id: "1100", discord_role_id: "7", group_id: "g-1", role: null };

    await act(async () => {
      await result.current.create.mutateAsync(input);
    });

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b-1/role-mappings", input);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(toast.success).toHaveBeenCalledWith(
      "Role mapped. People who hold it are placed at their next message to the bot.",
    );
  });

  it("deletes a mapping, and says why when that is refused", async () => {
    const { result } = renderHook(() => useDiscordRoleMappings("b-1"), { wrapper });

    await act(async () => {
      await result.current.remove.mutateAsync("m-1");
    });
    expect(apiClient.delete).toHaveBeenCalledWith("/channels/bots/b-1/role-mappings/m-1");
    expect(toast.success).toHaveBeenCalledWith("Mapping deleted");

    vi.mocked(apiClient.delete).mockRejectedValue(
      new ApiError(403, "You cannot remove a mapping to a role your own does not outrank"),
    );
    await act(async () => {
      await result.current.remove.mutateAsync("m-1").catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledWith(
      "You cannot remove a mapping to a role your own does not outrank",
    );
  });
});

describe("useDiscordServers", () => {
  it("asks Discord only while the form that needs it is open", async () => {
    const servers = [{ id: "1100", name: "Acme HQ", roles: [{ id: "7", name: "Finance" }] }];
    vi.mocked(apiClient.get).mockResolvedValue({ items: servers, total: 1 });

    const closed = renderHook(() => useDiscordServers("b-1", false), { wrapper });
    expect(closed.result.current.servers).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();

    const open = renderHook(() => useDiscordServers("b-1", true), { wrapper });
    await waitFor(() => expect(open.result.current.servers).toEqual(servers));
    expect(apiClient.get).toHaveBeenCalledWith("/channels/bots/b-1/discord-servers");
  });
});
