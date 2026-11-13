import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { skillSession } from "@/test-utils/skill-improvement";
import type { SkillProblems } from "@/types/skill-improvement";
import { SkillUnderstand } from "./skill-understand";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const PROBLEMS: SkillProblems = {
  problems: [
    {
      title: "Refund window misquoted",
      summary: "The skill says 30 days where the policy says 14.",
      runs: 4,
      agents: [
        { id: "a1", name: "Support", runs: 3 },
        { id: "a2", name: "Refunds", runs: 1 },
      ],
      hidden_agents: 1,
      examples: [
        { run_id: "r0", quote: null },
        { run_id: "r1", quote: "Can I return this after three weeks?" },
      ],
      hidden_examples: 3,
    },
  ],
  not_the_skill: 2,
  not_a_problem: 1,
  usage_unknown: 5,
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<SkillUnderstand session={skillSession()} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("SkillUnderstand", () => {
  it("names each problem and the agents it occurs in", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(PROBLEMS);
    mount();

    expect(await screen.findByText("Refund window misquoted")).toBeVisible();
    expect(
      screen.getByText("In 4 answers, at Support (3) and Refunds (1) and 1 agent you can't see."),
    ).toBeVisible();
    expect(screen.getByText("Can I return this after three weeks?")).toBeVisible();
    expect(screen.getByText("+3 hidden examples")).toBeVisible();
    expect(
      screen.getByText(
        "1 problem with the skill, 2 answers whose trouble lies elsewhere, 1 that were fine.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/5 answers are from before skill loads/)).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/k1/improvements/s1/evidence");
  });

  it("says when nothing points at the skill", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      ...PROBLEMS,
      problems: [],
      not_the_skill: 0,
      not_a_problem: 0,
      usage_unknown: 0,
    });
    mount();

    expect(await screen.findByText("No problem with the skill found.")).toBeVisible();
    expect(screen.queryByText(/before skill loads/)).toBeNull();
  });

  it("says when the problems cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Boom", { error: { code: "INTERNAL", message: "Boom" } }),
    );
    mount();

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });
});
