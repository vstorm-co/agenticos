import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { ImprovementAwaiting } from "@/types/improvement";
import type { SkillImprovementAwaiting } from "@/types/skill-improvement";
import { ImprovementsWaitingWidget } from "./improvements-waiting";

const state = vi.hoisted(() => ({
  sessions: [] as ImprovementAwaiting[],
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-improvements", () => ({ useImprovementsAwaiting: () => state }));
const skills = vi.hoisted(() => ({
  sessions: [] as SkillImprovementAwaiting[],
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-skill-improvement", () => ({ useSkillImprovementsAwaiting: () => skills }));

const PERIOD: Period = { preset: "30d", from: "2026-09-27", to: "2026-10-26" };

function widget() {
  return render(
    <TooltipProvider>
      <ImprovementsWaitingWidget title="Improvements waiting for you" hint="" period={PERIOD} />
    </TooltipProvider>,
  );
}

function waiting(overrides: Partial<ImprovementAwaiting>): ImprovementAwaiting {
  return {
    id: "s1",
    agent_id: "a1",
    agent_name: "Refund desk",
    status: "waiting",
    stage: "classifying",
    iteration: 1,
    max_iterations: 3,
    created_at: "2026-10-27T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  state.sessions = [];
  state.isLoading = false;
  state.error = null;
  state.refetch = vi.fn();
  skills.sessions = [];
  skills.isLoading = false;
  skills.error = null;
  skills.refetch = vi.fn();
});

describe("ImprovementsWaitingWidget", () => {
  it("lists each session with what it waits for, and opens it at that step", () => {
    state.sessions = [
      waiting({}),
      waiting({ id: "s2", agent_id: "a2", agent_name: "Sales", stage: "filtering" }),
      waiting({ id: "s3", agent_id: "a3", agent_name: "Support", status: "ready" }),
      waiting({
        id: "s4",
        agent_id: "a4",
        agent_name: "Billing",
        stage: "filtering",
        next_step_blocked: { reason: "missing_holdout", needed: 1 },
      }),
    ];
    widget();
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Refund deskLook at what went wrongOpen",
      "SalesReview the changesOpen",
      "SupportReview the resultOpen",
      "BillingBlocked: end it and start a new oneOpen",
    ]);
    expect(within(rows[1]!).getByRole("link", { name: "Sales" })).toHaveAttribute(
      "href",
      "/agents/a2",
    );
    expect(within(rows[1]!).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/agents/a2/improve/s2",
    );
  });

  it("shows only the newest five", () => {
    state.sessions = Array.from({ length: 7 }, (_, index) =>
      waiting({ id: `s${index}`, agent_name: `Agent ${index}` }),
    );
    widget();
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
  });

  it("says nothing waits, loads, and retries a failed read", async () => {
    const view = widget();
    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
    state.isLoading = true;
    view.rerender(
      <TooltipProvider>
        <ImprovementsWaitingWidget title="Improvements waiting for you" hint="" period={PERIOD} />
      </TooltipProvider>,
    );
    expect(screen.queryByText("Nothing waiting")).not.toBeInTheDocument();
    state.isLoading = false;
    state.error = new Error("Unavailable");
    view.rerender(
      <TooltipProvider>
        <ImprovementsWaitingWidget title="Improvements waiting for you" hint="" period={PERIOD} />
      </TooltipProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(state.refetch).toHaveBeenCalled();
  });

  it("lists a skill's sessions beside the agents', newest first", () => {
    state.sessions = [waiting({ created_at: "2026-10-27T10:00:00Z" })];
    skills.sessions = [
      {
        id: "k9",
        skill_id: "sk1",
        skill_name: "returns-policy",
        fork_id: "f1",
        line_name: "Returns",
        status: "waiting",
        stage: "filtering",
        iteration: 1,
        max_iterations: 3,
        created_at: "2026-10-28T10:00:00Z",
      },
      {
        id: "k8",
        skill_id: "sk2",
        skill_name: "tone",
        fork_id: null,
        line_name: "main",
        status: "ready",
        stage: null,
        iteration: 1,
        max_iterations: 3,
        created_at: "2026-10-26T10:00:00Z",
      },
    ];
    widget();

    const rows = screen.getAllByRole("listitem");
    expect(rows[0]!.textContent).toBe("returns-policy · fork “Returns”Review the changesOpen");
    expect(rows[2]!.textContent).toBe("tone · mainReview the resultOpen");
    expect(within(rows[0]!).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/skills/sk1/improve/k9",
    );
  });

  it("retries both reads when the skills' fails", async () => {
    skills.error = new Error("Unavailable");
    widget();

    await userEvent.click(screen.getByRole("button", { name: /try again|retry/i }));
    expect(state.refetch).toHaveBeenCalled();
    expect(skills.refetch).toHaveBeenCalled();
  });
});
