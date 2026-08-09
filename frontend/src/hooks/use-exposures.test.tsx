import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useExposures } from "./use-exposures";
import { apiClient } from "@/lib/api-client";
import type { Exposure } from "@/types/exposures";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function exposure(overrides: Partial<Exposure> = {}): Exposure {
  return {
    id: "e1",
    agent_id: "a1",
    surface: "slack",
    channel_bot_id: "b1",
    channel_bot_name: "Acme Support",
    environment_id: null,
    session_scope: null,
    is_active: true,
    created_at: null,
    ...overrides,
  };
}

function serve(exposures: Exposure[], targetIds: string[] = []) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/targets")) {
      return {
        items: targetIds.map((id) => ({ id, platform: "slack", name: id, is_active: true })),
        total: targetIds.length,
      };
    }
    return { items: exposures, total: exposures.length };
  });
}

async function hook() {
  const { result } = renderHook(() => useExposures("a1"), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result;
}

/**
 * The bindings between one agent and the channel bots it answers on.
 *
 * Two rules are load-bearing and neither is visible in the panel: each PATCH
 * carries exactly one field, because the server applies what it was sent and a
 * pause that also echoed `environment_id` would overwrite a rebinding somebody
 * made in between; and every mutation re-reads rather than patching the cache,
 * because the bot's name is resolved server-side.
 */
describe("useExposures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serve([exposure()]);
  });

  it("does not fetch until an agent is selected", () => {
    renderHook(() => useExposures(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the bindings and the bots separately", async () => {
    // Merging them would re-fetch a list that changes almost never every time a
    // binding moved.
    await hook();

    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/exposures");
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/exposures/targets");
  });

  it("offers only bots the agent is not already on", async () => {
    serve([exposure({ channel_bot_id: "b1" })], ["b1", "b2"]);
    const result = await hook();

    await waitFor(() => expect(result.current.available).toHaveLength(1));
    expect(result.current.available[0]?.id).toBe("b2");
  });

  it("names the new place once the server has resolved it", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockResolvedValue(exposure({ channel_bot_name: "Ops bot" }));
    const result = await hook();

    await result.current.expose.mutateAsync("b2");

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/exposures", { channel_bot_id: "b2" });
    expect(toast.success).toHaveBeenCalledWith("Now available on Ops bot");
  });

  it("sends only is_active when pausing", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ is_active: false }));
    const result = await hook();

    await result.current.setActive.mutateAsync({ exposureId: "e1", isActive: false });

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/exposures/e1", { is_active: false });
    expect(toast.success).toHaveBeenCalledWith("Paused on Acme Support");
  });

  it("says a binding is answering again when it is resumed", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ is_active: true }));
    const result = await hook();

    await result.current.setActive.mutateAsync({ exposureId: "e1", isActive: true });

    expect(toast.success).toHaveBeenCalledWith("Answering again on Acme Support");
  });

  it("sends only environment_id when rebinding, including the null", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(exposure());
    const result = await hook();

    await result.current.setEnvironment.mutateAsync({ exposureId: "e1", environmentId: null });

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/exposures/e1", {
      environment_id: null,
    });
  });

  it("re-reads the bindings after one is removed", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const result = await hook();

    await result.current.revoke.mutateAsync("e1");

    expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1/exposures/e1");
    expect(toast.success).toHaveBeenCalledWith("No longer available there");
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/exposures"));
  });

  it("surfaces the server's refusal on every mutation instead of failing silently", async () => {
    // `agents:publish` is enforced server-side; a viewer who got this far learns
    // it from the toast, not from a panel that simply does nothing.
    const { toast } = await import("sonner");
    const refused = new Error("You cannot publish this agent");
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    vi.mocked(apiClient.patch).mockRejectedValue(refused);
    vi.mocked(apiClient.delete).mockRejectedValue(refused);
    const result = await hook();

    await expect(result.current.expose.mutateAsync("b2")).rejects.toThrow(refused);
    await expect(
      result.current.setActive.mutateAsync({ exposureId: "e1", isActive: false }),
    ).rejects.toThrow(refused);
    await expect(
      result.current.setEnvironment.mutateAsync({ exposureId: "e1", environmentId: "env-1" }),
    ).rejects.toThrow(refused);
    await expect(result.current.revoke.mutateAsync("e1")).rejects.toThrow(refused);

    expect(toast.error).toHaveBeenCalledTimes(4);
    expect(toast.error).toHaveBeenCalledWith("You cannot publish this agent");
  });
});
