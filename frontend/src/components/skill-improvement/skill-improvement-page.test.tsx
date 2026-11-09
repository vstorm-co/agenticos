import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { checkAgent, skillCheck, skillSession } from "@/test-utils/skill-improvement";
import type { SkillContinuationEstimate } from "@/types/skill-improvement";

const checkAgentRunning = () => checkAgent("Support", "running");
const END = "End without changes";
import { SkillImprovementPage } from "./skill-improvement-page";

const state = vi.hoisted(() => ({
  step: null as string | null,
  runsView: true,
  canEdit: true,
  session: null as unknown,
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(state.step === null ? {} : { step: state.step }),
  usePathname: () => "/skills/k1/improve/s1",
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.runsView, isLoading: false }),
}));
vi.mock("@/hooks/use-organizations", async (original) => ({
  ...(await original<typeof import("@/hooks/use-organizations")>()),
  useOrganizationList: () => ({ data: [] }),
}));
vi.mock("./skill-understand", () => ({ SkillUnderstand: () => <p>understand</p> }));
vi.mock("@/components/improvement/attempt-changes", () => ({
  AttemptChanges: () => <p>attempt changes</p>,
}));
vi.mock("@/components/improvement/tried-changes", () => ({
  TriedChanges: () => <p>tried changes</p>,
}));
vi.mock("./skill-start", () => ({ SkillStart: () => <p>start a session</p> }));
vi.mock("./check-again", () => ({ CheckAgain: () => <p>check again</p> }));
vi.mock("@/components/improvement/next-step", () => ({
  NextStep: ({ detail }: { detail?: (quote: SkillContinuationEstimate) => ReactNode }) => (
    <div>
      {detail?.({
        mode: "next_step",
        number: 1,
        total_usd: "0.10",
        budget_usd: "1.00",
        affordable: true,
        candidate_hash: "h",
        check_estimate: { ...skillCheck(), agents: [checkAgent("Support", "queued")] },
      })}
    </div>
  ),
}));

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/skills/k1")
      return {
        id: "k1",
        name: "returns-policy",
        description: "Returns.",
        content: "",
        category: null,
        version: 12,
        latest_version_id: "m12",
        can_edit: state.canEdit,
        visibility: "org",
        owner_user_id: null,
      };
    if (path === "/skills/k1/improvements/s1") {
      if (state.session instanceof Error) throw state.session;
      return state.session;
    }
    throw new ApiError(404, "None");
  });
}

function mount(sessionId = "s1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<SkillImprovementPage skillId="k1" sessionId={sessionId} forkId={null} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.step = null;
  state.runsView = true;
  state.canEdit = true;
  state.session = skillSession();
  serve();
});

describe("SkillImprovementPage", () => {
  it("shows each agent's result and leads on to the decision", async () => {
    state.step = "result";
    mount();

    expect(await screen.findByText("How each agent did")).toBeVisible();
    expect(await screen.findByRole("button", { name: "Details of Support" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Decide what to do" }));

    expect(
      await screen.findByRole("button", { name: "Apply as the next version of main" }),
    ).toBeVisible();
  });

  it("follows the line's check while it runs", async () => {
    state.step = "check";
    state.session = skillSession({
      check: skillCheck({ verdict: null, agents: [checkAgentRunning()], finished_at: null }),
    });
    mount();

    expect(await screen.findByText("Checking each agent")).toBeVisible();
    expect(await screen.findByText("Checking")).toBeVisible();
    expect(screen.getByText("Line: main")).toBeVisible();
  });

  it("waits for the check before naming any result", async () => {
    state.step = "check";
    state.session = skillSession({ check: null });
    mount();

    expect(await screen.findByText(/has not started yet/)).toBeVisible();
  });

  it("draws Understand and the tried changes from the shared steps", async () => {
    state.step = "understand";
    mount();
    expect(await screen.findByText("understand")).toBeVisible();
  });

  it("shows the changes a finished attempt tried", async () => {
    state.step = "changes";
    mount();
    expect(await screen.findByText("tried changes")).toBeVisible();
  });

  it("lets the person tick and reword at the Changes stop", async () => {
    state.session = skillSession({ status: "waiting", stage: "filtering" });
    mount();
    expect(await screen.findByText("attempt changes")).toBeVisible();
  });

  it("keeps a closed session's result to read, with no decision left", async () => {
    state.step = "accept";
    state.session = skillSession({ status: "published", finished_at: "2026-11-02T11:00:00Z" });
    mount();

    expect(await screen.findByText(/This session is closed/)).toBeVisible();
  });

  it("opens the start of a new session", async () => {
    mount("new");
    expect(await screen.findByText("start a session")).toBeVisible();
  });

  it("refuses a reader without runs, pointing back to the skill", async () => {
    state.runsView = false;
    mount();

    expect(await screen.findByRole("alert")).toHaveTextContent(/needs edit access/);
    expect(screen.getByRole("link", { name: "Open the skill" })).toHaveAttribute(
      "href",
      "/skills/k1",
    );
  });

  it("refuses to start a session for a reader who may not edit the skill", async () => {
    state.canEdit = false;
    mount("new");

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByText("start a session")).toBeNull();
  });

  it("says when the session cannot be read", async () => {
    state.session = new ApiError(500, "Gone", { error: { code: "INTERNAL", message: "Gone" } });
    mount();

    expect(await screen.findByText("Gone")).toBeVisible();
    state.session = skillSession();
    await userEvent.click(screen.getByRole("button", { name: "Try reading again" }));
    expect(await screen.findByText("Line: main")).toBeVisible();
  });

  it("marks what an ended session wrote and checked as done, and its end as ended", async () => {
    state.session = skillSession({ status: "rejected", best_iteration_id: null });
    mount();

    expect(await screen.findByRole("button", { name: "Changes" })).toHaveAccessibleDescription(
      "Done",
    );
    expect(screen.getByRole("button", { name: "Accept" })).toHaveAccessibleDescription(
      "Ended without changes",
    );
  });

  it("leaves a result with nothing to accept to improve further or end", async () => {
    state.step = "result";
    state.session = skillSession({
      status: "stopped",
      best_iteration_id: null,
      check: skillCheck({ verdict: "no_better", outcomes: ["improve_further", "discard"] }),
      outcomes: ["improve_further", "discard"],
    });
    mount();

    expect(await screen.findByText("How each agent did")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Decide what to do" })).toBeNull();
    expect(screen.getByRole("button", { name: END })).toBeVisible();
  });

  it("shows a reader who may not edit the skill an open session with no decision", async () => {
    state.canEdit = false;
    state.step = "accept";
    mount();

    expect(await screen.findByText(/No agent got worse/)).toBeVisible();
    expect(screen.queryByRole("button", { name: /Apply/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add test questions" })).toBeNull();
  });

  it("leaves a reader who may not edit the skill nothing to continue at the result", async () => {
    state.canEdit = false;
    state.step = "result";
    state.session = skillSession({ status: "stopped", best_iteration_id: null });
    mount();

    expect(await screen.findByText("How each agent did")).toBeVisible();
    expect(screen.queryByRole("button", { name: END })).toBeNull();
  });

  it("names the agents the next check runs on at the Changes stop", async () => {
    state.session = skillSession({ status: "waiting", stage: "filtering" });
    mount();

    expect(await screen.findByText("It will be checked on 1 agent: Support.")).toBeVisible();
  });

  it("says Understand and Changes are still being written while the session runs", async () => {
    state.session = skillSession({ status: "running", stage: "analyzing", check: null });
    mount();
    expect(
      await screen.findByText(
        "Reading the answers that loaded this skill and were rated down or failed, and what in the skill they point to…",
      ),
    ).toBeVisible();

    cleanup();
    state.step = "changes";
    state.session = skillSession({ status: "running", stage: "drafting", check: null });
    mount();
    expect(await screen.findByText(/Writing the changes/)).toBeVisible();
  });

  it("says when the skill cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Down", { error: { code: "INTERNAL", message: "Down" } }),
    );
    mount();

    expect(await screen.findByText("Down")).toBeVisible();
  });

  it("offers Check again at a result its line moved past", async () => {
    state.step = "result";
    state.session = skillSession({ stale: true });
    mount();

    expect(await screen.findByText("check again")).toBeVisible();
  });

  it("offers a reader no Check again", async () => {
    state.canEdit = false;
    state.step = "result";
    state.session = skillSession({ stale: true });
    mount();

    expect(await screen.findByText("How each agent did")).toBeVisible();
    expect(screen.queryByText("check again")).toBeNull();
  });

  it("says the line moved under the changes it stops at", async () => {
    state.session = skillSession({ status: "waiting", stage: "filtering", stale: true });
    mount();

    expect(await screen.findByText(/got a newer version since these changes/)).toBeVisible();
  });
});
