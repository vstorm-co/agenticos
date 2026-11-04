import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { ReadOnlyProvider } from "@/components/improvement/read-only";
import { checkAgent, skillCheck, skillSession } from "@/test-utils/skill-improvement";
import type { SkillCheck } from "@/types/skill-checks";
import type { SkillImprovement } from "@/types/skill-improvement";
import { SkillAccept } from "./skill-accept";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("./check-again", () => ({ CheckAgain: () => <p>check again</p> }));
vi.mock("@/components/improvement/continue-session", () => ({
  ContinueSession: ({ lead }: { lead: ReactNode }) => (
    <div>
      {lead}
      <button>Try again</button>
    </div>
  ),
}));

function mount(
  check: SkillCheck,
  session: SkillImprovement = skillSession(),
  readOnly: "viewOnly" | null = null,
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const measured = { ...session, check, outcomes: check.outcomes };
  render(<SkillAccept session={measured} check={check} onStarted={vi.fn()} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ReadOnlyProvider value={readOnly}>{children}</ReadOnlyProvider>
      </QueryClientProvider>
    ),
  });
}

const confirm = () =>
  userEvent.click(
    screen.getByLabelText("I have reviewed the selected changes and want to apply them."),
  );

const BLOCKED = skillCheck({
  agents: [checkAgent("Support", "better"), checkAgent("Refunds", "worse")],
  verdict: "blocked",
  outcomes: ["improve_further", "apply_and_pin", "fork_for_helped", "discard"],
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "None"));
  vi.mocked(apiClient.post).mockResolvedValue(skillSession());
});

describe("SkillAccept", () => {
  it("applies a change that made nobody worse", async () => {
    mount(skillCheck());

    expect(screen.getByText("No agent got worse and at least one got better.")).toBeVisible();
    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Apply as the next version of main" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/s1/apply", {
      confirmed: true,
      acknowledge_unknown: false,
      pin_worse: false,
    });
  });

  it("offers pinning the worse and forking for the helped when somebody got worse", async () => {
    mount(BLOCKED);

    expect(
      screen.getByRole("button", { name: "Apply, and keep Refunds on the version it has" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /next version/ })).toBeNull();
    await userEvent.clear(screen.getByLabelText("Name of the new fork"));
    await userEvent.type(screen.getByLabelText("Name of the new fork"), "Returns");
    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Make a fork with this change for Support" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/s1/fork", {
      confirmed: true,
      name: "Returns",
      acknowledge_unknown: false,
    });
  });

  it.each([
    ["no_better", ["improve_further", "fork_for_helped", "discard"], false],
    ["blocked", ["improve_further", "apply_and_pin", "fork_for_helped", "discard"], true],
  ] as const)(
    "offers no fork, and confirms only what it offers, when nobody got better (%s)",
    (verdict, outcomes, confirms) => {
      mount(
        skillCheck({
          agents: [checkAgent("Support", "no_change"), checkAgent("Refunds", "no_change")],
          verdict,
          outcomes: [...outcomes],
        }),
      );

      expect(screen.queryByRole("button", { name: /Make a fork/ })).toBeNull();
      expect(
        screen.queryAllByLabelText("I have reviewed the selected changes and want to apply them."),
      ).toHaveLength(confirms ? 1 : 0);
    },
  );

  it("applies while keeping the agents it made worse on their version", async () => {
    mount(BLOCKED);

    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Apply, and keep Refunds on the version it has" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/s1/apply", {
      confirmed: true,
      acknowledge_unknown: false,
      pin_worse: true,
    });
  });

  it("says why a fork line offers only improving further or discarding", () => {
    mount(
      { ...BLOCKED, outcomes: ["improve_further", "discard"] },
      skillSession({ fork_id: "f1", line_name: "Returns" }),
    );

    expect(screen.getByText(/On a fork, the agents that got worse/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("holds the decision until the unknown agents are acknowledged", async () => {
    mount(
      skillCheck({
        agents: [
          checkAgent("Support", "better"),
          checkAgent("Billing", "unknown", { unknown_reason: "no_questions" }),
        ],
        verdict: "needs_ack",
      }),
    );

    const apply = screen.getByRole("button", { name: "Apply as the next version of main" });
    expect(apply).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Add test questions" })).toBeVisible();
    await confirm();
    expect(apply).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I know 1 agent could not be checked \(Billing\)/));
    await userEvent.click(apply);

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/k1/improvements/s1/apply",
      expect.objectContaining({ acknowledge_unknown: true }),
    );
  });

  it("names what refused the decision", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "This check was already decided", {
        error: {
          code: "CONCURRENT_CHANGE",
          message: "This check was already decided",
          details: { proposal_id: "p1" },
        },
      }),
    );
    mount(skillCheck({ warnings: ["within_noise"] }));

    expect(screen.getByText(/changed within the test's noise/)).toBeVisible();
    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Apply as the next version of main" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("This check was already decided");
    expect(screen.queryByText("check again")).toBeNull();
  });

  it("holds a change until the person confirms they reviewed it", async () => {
    mount(skillCheck());

    const apply = screen.getByRole("button", { name: "Apply as the next version of main" });
    expect(apply).toBeDisabled();
    await confirm();
    expect(apply).toBeEnabled();
  });

  it("acknowledges unknown agents it may not name without an empty list", () => {
    mount(skillCheck({ agents: [checkAgent("Sales", "no_change")], hidden: 1, hidden_unknown: 1 }));

    expect(
      screen.getByLabelText(
        "I know 1 agent could not be checked, and it gets the change all the same.",
      ),
    ).toBeVisible();
  });

  it("shows a reader who may not edit the skill the verdict and no decision", () => {
    mount(BLOCKED, skillSession(), "viewOnly");

    expect(screen.getByText(/got worse/)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByLabelText("Name of the new fork")).toBeNull();
  });

  it("offers Check again in place of the decisions on a result its line moved past", () => {
    mount(skillCheck(), skillSession({ stale: true }));

    expect(screen.getByText("check again")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  });

  it("offers Check again once a decision is refused because the line moved", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "Changed since this was checked", {
        error: {
          code: "CONCURRENT_CHANGE",
          message: "Changed since this was checked",
          details: { check_id: "c1", version: 13 },
        },
      }),
    );
    mount(skillCheck());

    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Apply as the next version of main" }),
    );

    expect(await screen.findByText("check again")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Changed since this was checked");
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
  });

  it.each([
    [
      "new agents on the line",
      new ApiError(409, "Joined", {
        error: {
          code: "CONCURRENT_CHANGE",
          message: "Joined",
          details: { agents: ["Billing"], hidden: 0 },
        },
      }),
      true,
    ],
    [
      "a check that is already decided",
      new ApiError(409, "Decided", { error: { code: "ALREADY_EXISTS", message: "Decided" } }),
      false,
    ],
    ["a failure that is not the API's", new Error("Offline"), false],
  ])(
    "offers Check again only when the refusal is %s that the check missed",
    async (_, failure, offered) => {
      vi.mocked(apiClient.post).mockRejectedValue(failure);
      mount(skillCheck());

      await confirm();
      await userEvent.click(
        screen.getByRole("button", { name: "Apply as the next version of main" }),
      );

      expect(await screen.findByRole("alert")).toBeVisible();
      expect(screen.queryByText("check again") !== null).toBe(offered);
    },
  );

  it("takes a checked catch-up into the fork, or returns its agents to main instead", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const check = skillCheck({ verdict: "no_better" });
    const returned = vi.fn();
    render(
      <SkillAccept
        session={skillSession({
          purpose: "catch_up",
          fork_id: "f1",
          line_name: "returns",
          check,
          outcomes: ["catch_up", "return_to_main", "discard"],
        })}
        check={check}
        onStarted={vi.fn()}
        onReturned={returned}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );

    expect(screen.getByText("No agent got worse with the merge.")).toBeVisible();
    const take = screen.getByRole("button", { name: "Make the merge the next version of returns" });
    expect(take).toBeDisabled();
    await confirm();
    await userEvent.click(take);
    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/k1/improvements/s1/apply", {
      confirmed: true,
      acknowledge_unknown: false,
      pin_worse: false,
    });

    const result = { agents: [], hidden: 0, remaining: 1, archived: false };
    vi.mocked(apiClient.post).mockResolvedValueOnce({ session: skillSession(), returned: result });
    await userEvent.click(
      screen.getByRole("button", { name: "Return the agents of returns to main instead" }),
    );
    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/k1/improvements/s1/return-to-main", {
      confirmed: true,
      acknowledge_unknown: false,
    });
    expect(returned).toHaveBeenCalledWith(result);
  });

  it("returns the agents to main without the acknowledgement a merge's decision needs", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const check = skillCheck({
      verdict: "needs_ack",
      agents: [checkAgent("Support", "better"), checkAgent("Refunds", "unknown")],
    });
    render(
      <SkillAccept
        session={skillSession({
          purpose: "catch_up",
          fork_id: "f1",
          line_name: "returns",
          check,
          outcomes: ["catch_up", "return_to_main", "discard"],
        })}
        check={check}
        onStarted={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
    await confirm();

    expect(
      screen.getByRole("button", { name: "Make the merge the next version of returns" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Return the agents of returns to main instead" }),
    ).toBeEnabled();
  });

  it("offers starting a merge again when its lines moved, never Check again", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const check = skillCheck();
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "Main changed while you were catching up. Start again to include it.", {
        error: {
          code: "LINE_MOVED",
          message: "Main changed while you were catching up. Start again to include it.",
          details: { moved: "main" },
        },
      }),
    );
    render(
      <SkillAccept
        session={skillSession({
          purpose: "catch_up",
          fork_id: "f1",
          line_name: "returns",
          check,
          outcomes: ["catch_up", "discard"],
        })}
        check={check}
        onStarted={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Make the merge the next version of returns" }),
    );

    expect(
      await screen.findByRole("button", { name: "Discard this merge and start again" }),
    ).toBeVisible();
    expect(screen.queryByText("check again")).not.toBeInTheDocument();
  });

  it("returns agents main alone could not check only once a person says they know", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const check = skillCheck({ verdict: "no_better" });
    render(
      <SkillAccept
        session={skillSession({
          purpose: "catch_up",
          fork_id: "f1",
          line_name: "returns",
          check,
          main_alone: "checked",
          main_alone_check: skillCheck({
            verdict: "needs_ack",
            agents: [checkAgent("Desk", "no_change"), checkAgent("Shop", "unknown")],
          }),
          outcomes: ["catch_up", "return_to_main", "discard"],
        })}
        check={check}
        onStarted={vi.fn()}
      />,
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={client}>{children}</QueryClientProvider>
        ),
      },
    );
    await confirm();
    const back = screen.getByRole("button", {
      name: "Return the agents of returns to main instead",
    });
    expect(back).toBeDisabled();

    await userEvent.click(
      screen.getByLabelText(
        "I know main alone could not be checked on 1 agent (Shop), and it returns to main all the same.",
      ),
    );
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      session: skillSession(),
      returned: { agents: [], hidden: 0, remaining: 0, archived: true },
    });
    await userEvent.click(back);

    expect(apiClient.post).toHaveBeenLastCalledWith("/skills/k1/improvements/s1/return-to-main", {
      confirmed: true,
      acknowledge_unknown: true,
    });
  });
});
