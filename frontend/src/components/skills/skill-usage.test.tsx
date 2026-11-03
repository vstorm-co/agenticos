import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { SkillUsage } from "@/types/skill-versions";
import { SkillUsageCard } from "./skill-usage";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const USAGE: SkillUsage = {
  days: 30,
  since: "2026-10-04T00:00:00Z",
  loads: 12,
  agents: [
    {
      agent_id: "a1",
      agent_name: "Gift shop counter",
      loads: 9,
      resource_reads: 2,
      workspace_reads: 0,
      last_loaded_at: "2026-11-02T10:00:00Z",
    },
    {
      agent_id: "a2",
      agent_name: "Wholesale desk",
      loads: 3,
      resource_reads: 0,
      workspace_reads: 0,
      last_loaded_at: null,
    },
  ],
  hidden_agents: 1,
  hidden_loads: 4,
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<SkillUsageCard skillId="s1" />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("SkillUsageCard", () => {
  it("counts each agent's use over thirty days, and the agents the reader cannot see", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(USAGE);
    mount();

    expect(await screen.findByRole("link", { name: "Gift shop counter" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
    expect(screen.getByText(/opened 9 times · 2 files read · last/)).toBeInTheDocument();
    expect(screen.getByText("opened 3 times")).toBeInTheDocument();
    expect(screen.getByText("1 agent you can't see opened it 4 times.")).toBeInTheDocument();
    expect(screen.getByText("Opened 16 times")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/usage?days=30");
  });

  it("says nobody used it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      ...USAGE,
      loads: 0,
      agents: [],
      hidden_agents: 0,
      hidden_loads: 0,
    });
    mount();
    expect(
      await screen.findByText(/No agent opened this skill in the last 30 days/),
    ).toBeInTheDocument();
  });

  it("says when its use cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(500, "Usage is down"));
    mount();
    expect(await screen.findByText("Usage is down")).toBeInTheDocument();
  });
});
