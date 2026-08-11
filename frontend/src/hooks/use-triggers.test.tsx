import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useTriggers } from "./use-triggers";
import { apiClient } from "@/lib/api-client";
import type { Trigger } from "@/types/triggers";

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

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: null,
    created_by_user_id: null,
    is_active: true,
    environment_id: null,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 300,
    cron_expression: null,
    event_source: null,
    event_config: {},
    prompt: "run",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: null,
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

async function hook() {
  const { result } = renderHook(() => useTriggers("a1"), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  return result;
}

/**
 * One agent's triggers, and the writes that change them.
 *
 * The load-bearing rule is not visible in the panel: a pause carries exactly
 * `is_active` and nothing read back, so it cannot overwrite an environment
 * somebody rebound in between - the same discipline exposures follows.
 */
describe("useTriggers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [trigger()], total: 1 });
  });

  it("does not fetch until an agent is selected", () => {
    renderHook(() => useTriggers(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the agent's triggers", async () => {
    await hook();

    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/triggers");
  });

  it("creates a trigger from the payload it is given", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    const result = await hook();

    await result.current.create.mutateAsync({
      prompt: "summarise",
      trigger_type: "schedule",
      schedule_kind: "interval",
      interval_seconds: 300,
    });

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/triggers", {
      prompt: "summarise",
      trigger_type: "schedule",
      schedule_kind: "interval",
      interval_seconds: 300,
    });
    expect(toast.success).toHaveBeenCalledWith("Trigger created");
  });

  it("sends only is_active when pausing, and names the act", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: false }));
    const result = await hook();

    await result.current.setActive.mutateAsync({ triggerId: "t1", isActive: false });

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", { is_active: false });
    expect(toast.success).toHaveBeenCalledWith("Trigger paused");
  });

  it("says a trigger is resumed when it is switched back on", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: true }));
    const result = await hook();

    await result.current.setActive.mutateAsync({ triggerId: "t1", isActive: true });

    expect(toast.success).toHaveBeenCalledWith("Trigger resumed");
  });

  it("patches only the fields it is handed", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ prompt: "new" }));
    const result = await hook();

    await result.current.update.mutateAsync({ triggerId: "t1", patch: { prompt: "new" } });

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", { prompt: "new" });
  });

  it("fires a trigger on demand through its run endpoint", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    const result = await hook();

    await result.current.runNow.mutateAsync("t1");

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/triggers/t1/run", {});
    expect(toast.success).toHaveBeenCalledWith("Running now");
  });

  it("re-reads the list after a trigger is removed", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const result = await hook();

    await result.current.remove.mutateAsync("t1");

    expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1/triggers/t1");
    expect(toast.success).toHaveBeenCalledWith("Trigger removed");
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/triggers"));
  });

  it("surfaces the server's refusal on every mutation instead of failing silently", async () => {
    const { toast } = await import("sonner");
    const refused = new Error("You cannot run this agent");
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    vi.mocked(apiClient.patch).mockRejectedValue(refused);
    vi.mocked(apiClient.delete).mockRejectedValue(refused);
    const result = await hook();

    await expect(
      result.current.create.mutateAsync({ prompt: "x", trigger_type: "schedule" }),
    ).rejects.toThrow(refused);
    await expect(
      result.current.update.mutateAsync({ triggerId: "t1", patch: { prompt: "x" } }),
    ).rejects.toThrow(refused);
    await expect(
      result.current.setActive.mutateAsync({ triggerId: "t1", isActive: false }),
    ).rejects.toThrow(refused);
    await expect(result.current.runNow.mutateAsync("t1")).rejects.toThrow(refused);
    await expect(result.current.remove.mutateAsync("t1")).rejects.toThrow(refused);

    expect(toast.error).toHaveBeenCalledTimes(5);
    expect(toast.error).toHaveBeenCalledWith("You cannot run this agent");
  });
});
