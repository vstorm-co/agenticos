import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { checkAgent, skillCheck, skillSession } from "@/test-utils/skill-improvement";
import type { SkillContinuationEstimate } from "@/types/skill-improvement";
import { CheckAgain } from "./check-again";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const QUOTE: SkillContinuationEstimate = {
  mode: "next_step",
  number: 1,
  total_usd: "0.40",
  budget_usd: "2.00",
  affordable: true,
  candidate_hash: "a".repeat(64),
  check_estimate: { ...skillCheck(), agents: [checkAgent("Support", "queued")] },
};

const ESTIMATE = "/skills/k1/improvements/s1/recheck/estimate";
const RECHECK = "/skills/k1/improvements/s1/recheck";

function mount(onStarted = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <CheckAgain
      session={skillSession({ stale: true, budget_usd: "2.00" })}
      onStarted={onStarted}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return onStarted;
}

function serve(recheck: () => Promise<unknown>, quotes: SkillContinuationEstimate[] = [QUOTE]) {
  let priced = 0;
  vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
    if (path === ESTIMATE) return quotes[Math.min(priced++, quotes.length - 1)];
    if (path === RECHECK) return recheck();
    throw new ApiError(404, "None");
  });
}

beforeEach(() => vi.clearAllMocks());

describe("CheckAgain", () => {
  it("prices the check on the line as it is, names its agents, and starts it", async () => {
    serve(async () => skillSession());
    const onStarted = mount();

    expect(screen.getByText("Pricing the check…")).toBeVisible();
    expect(await screen.findByText("It will be checked on 1 agent: Support.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Check again · up to $0.40" }));

    expect(apiClient.post).toHaveBeenCalledWith(RECHECK, {
      confirmed: true,
      budget_usd: "2.00",
      estimate_usd: "0.40",
      candidate_hash: "a".repeat(64),
    });
    expect(onStarted).toHaveBeenCalled();
  });

  it("shows the new price when it moved before the press reached the server", async () => {
    serve(async () => {
      throw new ApiError(409, "Moved");
    }, [QUOTE, { ...QUOTE, total_usd: "0.55" }]);
    const onStarted = mount();

    await userEvent.click(await screen.findByRole("button", { name: /Check again/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("up to $0.55");
    expect(screen.getByRole("button", { name: "Check again · up to $0.55" })).toBeEnabled();
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("says why a check was refused", async () => {
    serve(async () => {
      throw new ApiError(400, "The edits no longer apply", {
        error: { code: "BAD_REQUEST", message: "The edits no longer apply" },
      });
    });
    mount();

    await userEvent.click(await screen.findByRole("button", { name: /Check again/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The edits no longer apply");
  });

  it("says when the moved price could not be read again", async () => {
    let priced = 0;
    vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
      if (path === ESTIMATE && priced++ === 0) return QUOTE;
      throw new ApiError(
        path === RECHECK ? 409 : 500,
        "Pricing is down",
        path === RECHECK ? undefined : { error: { code: "INTERNAL", message: "Pricing is down" } },
      );
    });
    mount();

    await userEvent.click(await screen.findByRole("button", { name: /Check again/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Pricing is down");
  });

  it("holds a check the session's limit does not cover until a raised limit is priced to cover it", async () => {
    vi.mocked(apiClient.post).mockImplementation(async (path: string, body?: unknown) => {
      const asked = (body as { budget_usd?: string }).budget_usd;
      if (path === ESTIMATE) return { ...QUOTE, budget_usd: asked, affordable: asked === "5" };
      if (path === RECHECK) return skillSession();
      throw new ApiError(404, "None");
    });
    mount();

    expect(await screen.findByText(/costs more than this session has left/)).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledWith(ESTIMATE, { budget_usd: "2.00" });
    const go = screen.getByRole("button", { name: /Check again/ });
    expect(go).toBeDisabled();
    const limit = screen.getByLabelText("Session spending limit (USD)");
    const raise = async (value: string) => {
      await userEvent.clear(limit);
      await userEvent.type(limit, value);
      await userEvent.click(screen.getByRole("button", { name: "Use this limit" }));
    };

    await raise("3");
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith(ESTIMATE, { budget_usd: "3" }));
    expect(go).toBeDisabled();

    await raise("5");
    await waitFor(() => expect(go).toBeEnabled());
    await userEvent.click(go);

    expect(apiClient.post).toHaveBeenCalledWith(
      RECHECK,
      expect.objectContaining({ budget_usd: "5" }),
    );
  });

  it("says when the check cannot be priced", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "No result to check", {
        error: { code: "BAD_REQUEST", message: "No result to check" },
      }),
    );
    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent("No result to check");
    expect(screen.getByRole("button", { name: "Check again" })).toBeDisabled();
  });

  it("drops a price that arrives after it was closed", async () => {
    let settle: (value: SkillContinuationEstimate) => void = () => {};
    let refuse: (reason: unknown) => void = () => {};
    vi.mocked(apiClient.post)
      .mockReturnValueOnce(new Promise((resolve) => (settle = resolve)))
      .mockReturnValueOnce(new Promise((_, reject) => (refuse = reject)));
    const client = new QueryClient();
    const first = render(
      <QueryClientProvider client={client}>
        <CheckAgain session={skillSession({ stale: true })} onStarted={vi.fn()} />
      </QueryClientProvider>,
    );
    first.unmount();
    settle(QUOTE);
    const second = render(
      <QueryClientProvider client={client}>
        <CheckAgain session={skillSession({ stale: true })} onStarted={vi.fn()} />
      </QueryClientProvider>,
    );
    second.unmount();
    refuse(new ApiError(500, "Late"));

    await Promise.resolve();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
