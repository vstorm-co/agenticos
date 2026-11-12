import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { ReadOnlyProvider } from "@/components/improvement/read-only";
import { checkAgent, skillCheck, skillSession } from "@/test-utils/skill-improvement";
import type { SkillCheck } from "@/types/skill-checks";
import type { SkillImprovement } from "@/types/skill-improvement";
import { SkillAccept } from "./skill-accept";

const permissions = vi.hoisted(() => ({ datasetsEdit: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => permissions.datasetsEdit, isLoading: false }),
}));

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
  onForked = vi.fn(),
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const measured = { ...session, check, outcomes: check.outcomes };
  render(<SkillAccept session={measured} check={check} onStarted={vi.fn()} onForked={onForked} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <ReadOnlyProvider value={readOnly}>{children}</ReadOnlyProvider>
      </QueryClientProvider>
    ),
  });
  return onForked;
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

/** The skill's agents as the fork dialog reads them, each changeable unless named locked. */
function serveAgents(locked: string[] = []) {
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url !== "/skills/k1/agents") throw new ApiError(404, "None");
    return {
      main_latest: { id: "v1", number: 1, fork_id: null },
      items: ["support", "refunds", "billing", "sales"].map((id) => ({
        agent: { id, name: id, slug: id },
        can_change: !locked.includes(id),
      })),
      hidden: 0,
    };
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  serveAgents();
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

  it("offers pinning the worse and a fork for the helped when somebody got worse", async () => {
    const forked = {
      session: skillSession(),
      fork: { id: "f9", name: "Returns" },
      moved: [],
      draft_only: [{ id: "support", name: "Support" }],
    };
    vi.mocked(apiClient.post).mockResolvedValue(forked);
    const onForked = mount(BLOCKED);

    expect(
      screen.getByRole("button", { name: "Apply, and keep Refunds on the version it has" }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /next version/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    await waitFor(() => expect(screen.getByLabelText("Support")).toBeChecked());
    expect(screen.getByLabelText("Refunds")).not.toBeChecked();
    await userEvent.clear(screen.getByLabelText("Name of the new fork"));
    await userEvent.type(screen.getByLabelText("Name of the new fork"), "Returns");
    await userEvent.click(
      await screen.findByRole("button", { name: "Make the fork and move 1 agent" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith("/skills/k1/improvements/s1/fork", {
      confirmed: true,
      name: "Returns",
      agent_ids: ["support"],
      acknowledge_unknown: false,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onForked).toHaveBeenCalledWith(forked);
  });

  it("offers a fork for the agents picked when nobody got better, with nothing to confirm", async () => {
    mount(
      skillCheck({
        agents: [checkAgent("Support", "no_change"), checkAgent("Refunds", "no_change")],
        verdict: "no_better",
        outcomes: ["improve_further", "fork_for_helped", "discard"],
      }),
    );

    expect(
      screen.queryByLabelText("I have reviewed the selected changes and want to apply them."),
    ).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    expect(screen.getByLabelText("Name of the new fork")).toHaveValue("Attempt 1");
    await waitFor(() => expect(screen.getByLabelText("Refunds")).toBeEnabled());
    expect(screen.getByLabelText("Support")).not.toBeChecked();
    await userEvent.click(screen.getByLabelText("Refunds"));
    await userEvent.click(
      await screen.findByRole("button", { name: "Make the fork and move 1 agent" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/k1/improvements/s1/fork",
      expect.objectContaining({ name: "Attempt 1", agent_ids: ["refunds"] }),
    );
  });

  it("makes a fork that moves no agent once every pick is cleared", async () => {
    mount(BLOCKED);

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    await waitFor(() => expect(screen.getByLabelText("Support")).toBeChecked());
    await userEvent.click(screen.getByLabelText("Support"));
    await userEvent.click(screen.getByRole("button", { name: "Make the fork, moving no agent" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/k1/improvements/s1/fork",
      expect.objectContaining({ name: "Support", agent_ids: [] }),
    );
  });

  it("draws each agent of the pick with its own face", async () => {
    mount(BLOCKED);

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));

    expect(apiClient.get).toHaveBeenCalledWith("/skills/k1/agents");
    for (const id of ["support", "refunds"]) {
      expect(
        screen.getByRole("dialog").querySelector(`[data-agent-avatar="${id}"]`),
      ).not.toBeNull();
    }
  });

  it("shows a helped agent the reader may not change but never sends it", async () => {
    serveAgents(["billing"]);
    mount({
      ...BLOCKED,
      agents: [
        checkAgent("Support", "better"),
        checkAgent("Billing", "better"),
        checkAgent("Refunds", "worse"),
      ],
    });

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    await waitFor(() => expect(screen.getByLabelText("Billing")).toBeDisabled());
    expect(screen.getByLabelText("Billing")).not.toBeChecked();
    expect(screen.getByText("You cannot change it: stays on its version")).toBeVisible();
    await userEvent.click(
      await screen.findByRole("button", { name: "Make the fork and move 1 agent" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/k1/improvements/s1/fork",
      expect.objectContaining({ agent_ids: ["support"] }),
    );
  });

  it("picks and sends nothing until it knows which agents the reader may change, and retries", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "The skill's agents could not be read", {
        error: { code: "INTERNAL", message: "The skill's agents could not be read" },
      }),
    );
    mount(BLOCKED);

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.getByLabelText("Support")).toBeDisabled();
    expect(screen.getByLabelText("Support")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Make the fork, moving no agent" })).toBeDisabled();

    serveAgents();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByLabelText("Support")).toBeChecked());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Make the fork and move 1 agent" })).toBeEnabled();
  });

  it("keeps the dialog and what was typed when the fork is refused", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "A fork named Returns exists", {
        error: { code: "ALREADY_EXISTS", message: "A fork named Returns exists" },
      }),
    );
    mount(BLOCKED);

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));
    await userEvent.clear(screen.getByLabelText("Name of the new fork"));
    await userEvent.type(screen.getByLabelText("Name of the new fork"), "Returns");
    await userEvent.click(
      await screen.findByRole("button", { name: "Make the fork and move 1 agent" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("A fork named Returns exists");
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(screen.getByLabelText("Name of the new fork")).toHaveValue("Returns");
  });

  it("leaves out of the pick the agents it may not move here, and says why", async () => {
    mount({
      ...BLOCKED,
      agents: [
        checkAgent("Support", "better"),
        checkAgent("Refunds", "worse", { via_specialist: "Refund checker" }),
      ],
      hidden: 2,
    });

    await userEvent.click(screen.getByRole("button", { name: "Save as a fork…" }));

    expect(screen.queryByLabelText("Refunds")).toBeNull();
    expect(screen.getByText(/1 agent reads the skill through a specialist/)).toBeVisible();
    expect(screen.getByText("2 agents you cannot see stay where they are.")).toBeVisible();
  });

  it("holds the fork until the unknown agents are acknowledged", async () => {
    mount({
      ...BLOCKED,
      agents: [
        checkAgent("Support", "better"),
        checkAgent("Billing", "unknown", { unknown_reason: "no_questions" }),
      ],
    });

    const open = screen.getByRole("button", { name: "Save as a fork…" });
    expect(open).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I know 1 agent could not be checked \(Billing\)/));
    await userEvent.click(open);
    await userEvent.click(
      await screen.findByRole("button", { name: "Make the fork and move 1 agent" }),
    );

    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills/k1/improvements/s1/fork",
      expect.objectContaining({ acknowledge_unknown: true }),
    );
  });

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
    expect(screen.queryByRole("button", { name: "Save as a fork…" })).toBeNull();
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
