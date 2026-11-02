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
      new ApiError(409, "The line moved", {
        error: { code: "CONCURRENT_CHANGE", message: "The line moved" },
      }),
    );
    mount(skillCheck({ warnings: ["within_noise"] }));

    expect(screen.getByText(/changed within the test's noise/)).toBeVisible();
    await confirm();
    await userEvent.click(
      screen.getByRole("button", { name: "Apply as the next version of main" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("The line moved");
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
});
