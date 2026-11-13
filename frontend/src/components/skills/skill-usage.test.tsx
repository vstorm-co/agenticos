import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { SkillUsage } from "@/types/skill-versions";
import { SkillUsageCard, usageDays } from "./skill-usage";
import { fromFirstLoad } from "./usage-chart";

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
      slug: "gift-shop",
      has_avatar: false,
      avatar_color: null,
      daily: [
        { date: "2026-11-01", loads: 0 },
        { date: "2026-11-02", loads: 9 },
      ],
    },
    {
      agent_id: "a2",
      agent_name: "Wholesale desk",
      loads: 3,
      resource_reads: 0,
      workspace_reads: 0,
      last_loaded_at: null,
      slug: "wholesale",
      has_avatar: false,
      avatar_color: 4,
      daily: [
        { date: "2026-11-01", loads: 3 },
        { date: "2026-11-02", loads: 0 },
      ],
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
    const row = (name: string) => screen.getByRole("link", { name }).closest("tr")!;
    expect(row("Gift shop counter")).toHaveTextContent(/92Nov 2, 2026/);
    expect(row("Wholesale desk")).toHaveTextContent("30Not yet");
    expect(row("Gift shop counter").querySelector("[data-agent-avatar='a1']")).not.toBeNull();
    expect(screen.getByRole("img", { name: "Loads per day, one line per agent" })).toBeVisible();
    expect(screen.getByText("1 agent you can't see opened it 4 times.")).toBeInTheDocument();
    expect(screen.getByText("Opened 16 times")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/usage?days=30");
  });

  it("says an agent that only named the skill's folder probably used it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      ...USAGE,
      agents: [{ ...USAGE.agents[1]!, loads: 0, workspace_reads: 2 }],
    });
    mount();

    const row = (await screen.findByRole("link", { name: "Wholesale desk" })).closest("tr")!;
    expect(row).toHaveTextContent("Probably: named its folder in 2 runs");
    expect(row).not.toHaveTextContent("Not yet");
  });

  it("overlays the agents picked on one chart, the busiest five to start with", async () => {
    const agents = Array.from({ length: 6 }, (_, index) => ({
      ...USAGE.agents[0]!,
      agent_id: `a${index}`,
      agent_name: `Agent ${index}`,
      loads: index,
      slug: `agent-${index}`,
      has_avatar: false,
      avatar_color: 3,
      daily: [],
    }));
    vi.mocked(apiClient.get).mockResolvedValue({ ...USAGE, agents });
    mount();

    const picker = await screen.findByRole("group", { name: "Agents on the chart" });
    const chip = (name: string) => within(picker).getByRole("button", { name });
    expect(chip("Agent 0")).toHaveAttribute("aria-pressed", "false");
    expect(chip("Agent 5")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: "Loads per day, one line per agent" })).toBeVisible();
    expect(
      screen.getByText("The agents picked did not load the skill in the last 30 days."),
    ).toBeVisible();

    await userEvent.click(chip("Agent 0"));
    expect(chip("Agent 0")).toHaveAttribute("aria-pressed", "true");
    for (const index of [0, 1, 2, 3, 4, 5]) await userEvent.click(chip(`Agent ${index}`));
    expect(screen.getByText("Pick an agent above to draw its line.")).toBeVisible();
    expect(chip("Agent 0").querySelector("[data-agent-avatar='a0']")).not.toBeNull();
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

describe("usageDays", () => {
  it("keys each agent's loads under it, a row per day, and dashes lines past five colours", () => {
    const agents = Array.from({ length: 7 }, (_, index) => ({
      ...USAGE.agents[0]!,
      agent_id: `a${index}`,
      agent_name: `Agent ${index}`,
      daily: index === 1 ? [{ date: "2026-11-01", loads: 4 }] : USAGE.agents[0]!.daily,
    }));
    const chart = usageDays({ ...USAGE, agents }, (day) => day.slice(5));

    expect(chart.days.map((day) => day.day)).toEqual(["11-01", "11-02"]);
    expect(chart.days.map((day) => day.a0)).toEqual([0, 9]);
    expect(chart.days.map((day) => day.a1)).toEqual([4, 0]);
    expect(chart.lines.map((line) => line.dash)).toEqual([
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      "6 3",
      "6 3",
    ]);
  });
});

describe("fromFirstLoad", () => {
  const days = [
    { day: "1", a: 0, b: 0 },
    { day: "2", a: 0, b: 3 },
    { day: "3", a: 0, b: 0 },
    { day: "4", a: 2, b: 0 },
  ];

  it("starts at the first day a picked agent loaded the skill, keeping the quiet days after", () => {
    expect(fromFirstLoad(days, new Set(["a", "b"])).map((day) => day.day)).toEqual(["2", "3", "4"]);
    expect(fromFirstLoad(days, new Set(["a"])).map((day) => day.day)).toEqual(["4"]);
  });

  it("leaves no days when the picked agents loaded it on none", () => {
    expect(fromFirstLoad(days, new Set(["c"]))).toEqual([]);
  });
});
