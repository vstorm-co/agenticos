import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { ImprovementAwaiting } from "@/types/improvement";
import type { SkillImprovementAwaiting } from "@/types/skill-improvement";
import type { BehindMain, BehindMainList } from "@/types/skill-merge";
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
const behind = vi.hoisted(() => ({
  behind: undefined as BehindMainList | undefined,
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
}));
const asked = vi.hoisted(() => ({ enabled: undefined as boolean | undefined, skillsView: true }));
vi.mock("@/hooks/use-skill-merge", () => ({
  useBehindMain: (options: { enabled: boolean }) => {
    asked.enabled = options.enabled;
    return behind;
  },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (permission: string) => permission !== "skills:view" || asked.skillsView,
  }),
}));

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
  behind.behind = undefined;
  behind.isLoading = false;
  behind.error = null;
  behind.refetch = vi.fn();
  asked.skillsView = true;
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
    skills.error = new Error("Unavailable");
    behind.error = new Error("Unavailable");
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

  it("keeps the agents' sessions listed when the skills' read fails", async () => {
    state.sessions = [waiting({})];
    skills.error = new Error("Unavailable");
    widget();

    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("Skill sessions could not be read.");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.refetch).toHaveBeenCalled();
    expect(skills.refetch).toHaveBeenCalled();
  });

  it("says the agents' read failed under the skills' sessions", () => {
    state.error = new Error("Unavailable");
    state.sessions = [waiting({})];
    widget();

    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Agent sessions could not be read.");
  });

  it("names a fork called main as a fork", () => {
    skills.sessions = [
      {
        id: "k9",
        skill_id: "sk1",
        skill_name: "returns-policy",
        fork_id: "f1",
        line_name: "main",
        status: "ready",
        stage: null,
        iteration: 1,
        max_iterations: 3,
        created_at: "2026-10-28T10:00:00Z",
      },
    ];
    widget();

    expect(screen.getByRole("link", { name: "returns-policy · fork “main”" })).toBeVisible();
  });

  it("lists what main left behind after the sessions, and catches a fork up from here", () => {
    state.sessions = [waiting({})];
    behind.behind = {
      items: [
        behindItem({
          kind: "fork",
          agent: null,
          fork: { id: "f1", name: "returns", base_number: 4, changes: 2 },
          agents: 2,
          behind_main: 3,
        }),
        behindItem({}),
        behindItem({
          agent: { id: "a9", name: "Billing", slug: "billing" },
          can_act: false,
          behind_main: 1,
        }),
      ],
      total: 3,
      hidden: 0,
    };
    widget();

    const rows = screen.getAllByRole("listitem");
    expect(rows.map((row) => row.textContent)).toEqual([
      "Refund deskLook at what went wrongOpen",
      "refunds · fork “returns”From v4 · 2 agents · 3 changes behind mainCatch up",
      "refunds · pinned in DeskOn v4 · 2 changes behind mainOpen",
      "refunds · pinned in BillingOn v4 · 1 change behind main",
    ]);
    expect(within(rows[1]!).getByRole("link", { name: "Catch up" })).toHaveAttribute(
      "href",
      "/skills/sk1/improve/new?fork=f1&merge=catch_up",
    );
    expect(within(rows[2]!).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/skills/sk1",
    );
    expect(within(rows[3]!).queryByRole("link", { name: "Open" })).not.toBeInTheDocument();
  });

  it("reads what main left behind only for a reader of skills, and opens a fork with nothing of its own", async () => {
    behind.behind = {
      items: [
        behindItem({
          kind: "fork",
          agent: null,
          fork: { id: "f2", name: "empty", base_number: 4, changes: 0 },
        }),
      ],
      total: 1,
      hidden: 0,
    };
    widget();
    expect(asked.enabled).toBe(true);
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/skills/sk1");

    asked.skillsView = false;
    behind.behind = undefined;
    skills.error = new Error("Unavailable");
    widget();
    expect(asked.enabled).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(skills.refetch).toHaveBeenCalled();
    expect(behind.refetch).not.toHaveBeenCalled();
  });

  it("keeps the sessions listed when what main left behind cannot be read", () => {
    state.sessions = [waiting({})];
    behind.error = new Error("Unavailable");
    widget();

    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent("What main left behind could not be read.");
  });
});

function behindItem(overrides: Partial<BehindMain>): BehindMain {
  return {
    kind: "pinned",
    skill: { id: "sk1", name: "refunds" },
    agent: { id: "a1", name: "Desk", slug: "desk" },
    via_specialist: null,
    fork: null,
    agents: 1,
    version: { id: "v4", number: 4 },
    main_latest: { id: "v6", number: 6 },
    behind_main: 2,
    can_act: true,
    ...overrides,
  } as BehindMain;
}
