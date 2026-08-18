import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useScheduleTemplates } from "./use-schedule-templates";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn() } };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

describe("useScheduleTemplates", () => {
  it("reads the seeded schedule-template catalog", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [
        {
          key: "daily-standup",
          label: "Daily standup",
          description: "Summarise overnight activity",
          prompt: "Summarise what happened overnight.",
          suggested_cadence: { schedule_kind: "interval", interval_seconds: 86400 },
        },
      ],
      total: 1,
    });

    const { result } = renderHook(() => useScheduleTemplates(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(apiClient.get).toHaveBeenCalledWith("/schedule-templates");
    expect(result.current.templates).toHaveLength(1);
    expect(result.current.templates[0]?.label).toBe("Daily standup");
  });

  it("answers with an empty list before the catalog arrives", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useScheduleTemplates(), { wrapper });

    expect(result.current.templates).toEqual([]);
    expect(result.current.isLoading).toBe(true);
  });
});
