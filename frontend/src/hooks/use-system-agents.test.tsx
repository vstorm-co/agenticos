import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSystemAgents } from "./use-system-agents";
import { listSystemAgents, updateSystemAgent } from "@/lib/system-agents-api";

vi.mock("@/lib/system-agents-api", () => ({
  listSystemAgents: vi.fn(),
  updateSystemAgent: vi.fn(),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org-1" }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const role = (name: "daily_briefing" | "memory_maintenance", enabled: boolean) => ({
  role: name,
  enabled,
  model_profile_id: null,
  model_label: null,
  monthly_budget_usd: null,
  spent_this_month: "0",
  managed_in: null,
  unavailable: null,
  runs: [],
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSystemAgents).mockResolvedValue([
    role("daily_briefing", true),
    role("memory_maintenance", false),
  ]);
});

describe("useSystemAgents", () => {
  it("reads only when asked to", async () => {
    renderHook(() => useSystemAgents(false), { wrapper });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(listSystemAgents).not.toHaveBeenCalled();
  });

  it("replaces the saved role in the cache without rereading", async () => {
    vi.mocked(updateSystemAgent).mockResolvedValue(role("memory_maintenance", true));
    const { result } = renderHook(() => useSystemAgents(true), { wrapper });
    await waitFor(() => expect(result.current.roles).toHaveLength(2));

    await act(() =>
      result.current.update.mutateAsync({
        role: "memory_maintenance",
        change: { enabled: true, model_profile_id: "m", monthly_budget_usd: null },
      }),
    );

    await waitFor(() => expect(result.current.roles?.[1]?.enabled).toBe(true));
    expect(result.current.roles?.[0]?.enabled).toBe(true);
    expect(listSystemAgents).toHaveBeenCalledTimes(1);
  });
});
