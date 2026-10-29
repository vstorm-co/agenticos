import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { ImprovementAwaiting } from "@/types/improvement";
import { ImprovementsWaitingWidget } from "./improvements-waiting";

const state = vi.hoisted(() => ({
  sessions: [] as ImprovementAwaiting[],
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-improvements", () => ({ useImprovementsAwaiting: () => state }));

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
});
