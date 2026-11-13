import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { skillSession } from "@/test-utils/skill-improvement";
import type { MergeKind, SkillMergeEstimate } from "@/types/skill-merge";
import { MergeStart } from "./merge-start";

const push = vi.fn();
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const ESTIMATE: SkillMergeEstimate = {
  line: { fork_id: "f1", name: "returns" },
  source_fork: null,
  base_version: { id: "m12", number: 12 },
  conflicts: 2,
  total_usd: "0.04",
  agents: 3,
  hidden_agents: 1,
  affordable: true,
};

let estimate: SkillMergeEstimate | Error = ESTIMATE;

function mount(kind: MergeKind = "catch_up") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<MergeStart skillId="k1" forkId="f1" kind={kind} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  estimate = ESTIMATE;
  vi.mocked(apiClient.get).mockResolvedValue([]);
  vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
    if (!path.endsWith("/estimate")) return skillSession({ id: "s9" });
    if (estimate instanceof Error) throw estimate;
    return estimate;
  });
});

describe("MergeStart", () => {
  it("says what a catch-up merges and costs, and starts it within the limit", async () => {
    mount();

    expect(
      await screen.findByRole("heading", { name: "Catch “returns” up with main" }),
    ).toBeVisible();
    expect(
      screen.getByText(
        "2 parts were changed on both sides. The assistant proposes a text for each, and you can change them.",
      ),
    ).toBeVisible();
    expect(screen.getByText("3 agents check the result.")).toBeVisible();
    expect(screen.getByText("1 more agent you cannot see reads this line.")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/k1/improvements", {
      params: { fork_id: "f1" },
    });
    const limit = screen.getByLabelText("Spending limit for the session (USD)");
    await userEvent.clear(limit);
    await userEvent.type(limit, "2");
    await userEvent.click(screen.getByRole("button", { name: "Start the catch-up" }));

    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/k1/forks/f1/catch-up", {
      budget_usd: "2",
    });
    expect(push).toHaveBeenCalledWith("/skills/k1/improve/s9");
  });

  it("moves a fork to main with nothing conflicting, a free start allowed", async () => {
    estimate = {
      ...ESTIMATE,
      line: { fork_id: null, name: "main" },
      source_fork: { fork_id: "f1", name: "returns" },
      conflicts: 0,
      total_usd: "0",
      hidden_agents: 0,
    };
    mount("to_main");

    expect(await screen.findByRole("heading", { name: "Move “returns” to main" })).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/k1/improvements", {
      params: { main: "true" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Start the move" }));
    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/k1/forks/f1/to-main", {
      budget_usd: "0.00",
    });
  });

  it("sends a line with an open session back to it instead of pricing another", async () => {
    vi.mocked(apiClient.get).mockResolvedValue([skillSession({ id: "s3", status: "waiting" })]);
    mount();

    expect(await screen.findByRole("link", { name: "Continue it" })).toHaveAttribute(
      "href",
      "/skills/k1/improve/s3",
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("says why there is nothing to merge, or why the start was refused", async () => {
    estimate = new ApiError(409, "Main has nothing the fork 'returns' does not have");
    mount();
    expect(
      await screen.findByText("Main has nothing the fork 'returns' does not have"),
    ).toBeVisible();
  });

  it("keeps the price on screen when the start is refused, and holds an unaffordable one", async () => {
    estimate = { ...ESTIMATE, affordable: false };
    mount();
    expect(await screen.findByText("The organization's budget does not cover this.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Start the catch-up" })).toBeDisabled();
  });

  it("says why a start was refused under its price", async () => {
    vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
      if (path.endsWith("/estimate")) return ESTIMATE;
      throw new ApiError(409, "A session is already open on this line");
    });
    mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start the catch-up" }));

    expect(await screen.findByText("A session is already open on this line")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Catch “returns” up with main" })).toBeVisible();
  });

  it("says why the line's sessions could not be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(500, "Unavailable"));
    mount();
    expect(await screen.findByText("Unavailable")).toBeVisible();
  });
});
