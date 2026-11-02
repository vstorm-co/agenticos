import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { checkAgent, skillSession } from "@/test-utils/skill-improvement";
import { SkillStart } from "./skill-start";

const push = vi.fn();
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const ESTIMATE = {
  proposal_usd: "0.02",
  eval_usd: "0.03",
  per_round_usd: "0.05",
  total_usd: "0.20",
  max_iterations: 3,
  cases: 10,
  evidence_runs: 12,
  estimated_minutes: 9,
  affordable: true,
  reason: null,
  agents: [
    checkAgent("Support", "queued"),
    checkAgent("Billing", "unknown", { unknown_reason: "no_budget" }),
  ],
  hidden_agents: 1,
  line: { fork_id: null, name: "main" },
};

function mount(forkId: string | null = null, fromRun: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<SkillStart skillId="k1" forkId={forkId} fromRun={fromRun} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue([]);
  vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
    path.endsWith("/estimate") ? ESTIMATE : skillSession({ id: "s9" }),
  );
});

describe("SkillStart", () => {
  it("names the agents it checks on and the ones it cannot, before anything is spent", async () => {
    mount();

    expect(await screen.findByText("It will be checked on 1 agent: Support.")).toBeVisible();
    expect(screen.getByText("Billing cannot be checked: its budget is spent.")).toBeVisible();
    expect(screen.getByText("1 more agent you can't see uses this line.")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/estimate", {
      fork_id: null,
    });
  });

  it("starts on the line with the limit set, and opens the session", async () => {
    mount("f1");

    await screen.findByText("It will be checked on 1 agent: Support.");
    await userEvent.clear(screen.getByLabelText(/Spending limit/));
    await userEvent.type(screen.getByLabelText(/Spending limit/), "0.5");
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements", {
      fork_id: "f1",
      budget_usd: "0.5",
    });
    expect(apiClient.get).toHaveBeenCalledWith("/skills/k1/improvements", {
      params: { fork_id: "f1" },
    });
    expect(push).toHaveBeenCalledWith("/skills/k1/improve/s9");
  });

  it("starts from the problems an agent's session handed over", async () => {
    mount(null, "run-7");

    await screen.findByText("It will be checked on 1 agent: Support.");
    await userEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/estimate", {
      fork_id: null,
      from_run: "run-7",
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/k1/improvements",
      expect.objectContaining({ fork_id: null, from_run: "run-7" }),
    );
  });

  it("sends the person to the line's open session instead of a second one", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([skillSession({ id: "s3", status: "waiting" })]);
    mount();

    expect(await screen.findByRole("link", { name: "Continue it" })).toHaveAttribute(
      "href",
      "/skills/k1/improve/s3",
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("holds the start when the organization cannot pay for it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ ...ESTIMATE, affordable: false, reason: null });
    mount();

    expect(await screen.findByText("The organization's budget does not cover this.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("says what refused the price", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "No agents", { error: { code: "VALIDATION", message: "No agents" } }),
    );
    mount();

    expect(await screen.findByText("No agents")).toBeInTheDocument();
  });

  it("says what refused the start, and stays", async () => {
    vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
      if (path.endsWith("/estimate")) return ESTIMATE;
      throw new ApiError(400, "Over budget", { error: { code: "BUDGET", message: "Over budget" } });
    });
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Start" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Over budget");
    expect(push).not.toHaveBeenCalled();
  });

  it("says when the line's sessions cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Boom", { error: { code: "INTERNAL", message: "Boom" } }),
    );
    mount();

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });
});
