import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { skillSession } from "@/test-utils/skill-improvement";
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
  line: { fork_id: null, name: "main" },
  base_version: { id: "m12", number: 12 },
  proposal_usd: "0.02",
  per_round_usd: "0.05",
  total_usd: "0.20",
  max_iterations: 3,
  evidence_runs: 12,
  usage_unknown: 4,
  agents: 2,
  hidden_agents: 1,
  estimated_minutes: 9,
  affordable: true,
  reason: null,
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
  it("says what it reads and how many agents the line serves, before anything is spent", async () => {
    mount();

    expect(
      await screen.findByText(
        "It reads 12 answers that loaded this line and were rated down or failed. The line serves 2 agents.",
      ),
    ).toBeVisible();
    expect(screen.getByText("1 more agent you can't see uses this line.")).toBeVisible();
    expect(screen.getByText(/4 answers are from before skill loads were recorded/)).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/estimate", {
      fork_id: null,
    });
  });

  it("fills in a limit for the first proposal and every attempt, and says what it caps", async () => {
    mount();

    expect(await screen.findByLabelText(/Spending limit/)).toHaveValue("0.35");
    expect(
      screen.getByText(
        "Up to $0.20 (estimate) to its first proposal; each attempt after it about $0.05, up to 3 attempts. The limit of $0.35 caps the whole session.",
      ),
    ).toBeVisible();
    await userEvent.clear(screen.getByLabelText(/Spending limit/));
    await userEvent.type(screen.getByLabelText(/Spending limit/), "1");
    expect(screen.getByText(/The limit of \$1\.00 caps the whole session/)).toBeVisible();
    await userEvent.clear(screen.getByLabelText(/Spending limit/));
    await userEvent.type(screen.getByLabelText(/Spending limit/), "abc");
    expect(screen.getByText(/The limit of \$0\.35 caps the whole session/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("starts on the line with the limit set, and opens the session", async () => {
    mount("f1");

    await screen.findByText(/It reads 12 answers/);
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

    await screen.findByText(/It reads 12 answers/);
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

  it("says a single answer it reads in the singular", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ ...ESTIMATE, evidence_runs: 1, agents: 1 });
    mount();

    expect(
      await screen.findByText(
        "It reads 1 answer that loaded this line and was rated down or failed. The line serves 1 agent.",
      ),
    ).toBeVisible();
  });

  it("holds the start up front when there is nothing to learn from, and says how to give some", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      ...ESTIMATE,
      evidence_runs: 0,
      reason: "no_evidence",
    });
    mount();

    expect(
      await screen.findByText(
        "No answer that loaded this line was rated down or failed yet, so there is nothing to learn from. Rate down an answer in chat where an agent used this skill, then start again.",
      ),
    ).toBeVisible();
    expect(screen.queryByText(/It reads/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Start" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open chat" }));
    expect(push).toHaveBeenCalledWith("/chat");
    expect(screen.queryByLabelText(/Spending limit/)).toBeNull();
  });

  it("holds the start while the limit is below the first proposal's estimate, and says so", async () => {
    mount();

    const limit = await screen.findByLabelText(/Spending limit/);
    await userEvent.clear(limit);
    await userEvent.type(limit, "0.1");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The limit is below what the session costs to its first proposal, $0.20.",
    );
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();

    await userEvent.clear(limit);
    await userEvent.type(limit, "0.2");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();
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

  it("sends a line whose test questions all come from the evidence to add others", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "Every case was taken from the conversations", {
        error: {
          code: "BAD_REQUEST",
          message: "Every case was taken from the conversations",
          details: { dataset_id: "d7", excluded: 3, reason: "all_evidence" },
        },
      }),
    );
    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Every question of this dataset comes from the conversations this change learned from, so none of them can test it.",
    );
    expect(
      screen.getByRole("link", { name: "Add questions from other conversations" }),
    ).toHaveAttribute("href", "/datasets/d7");
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
