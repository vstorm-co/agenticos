import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { checkAgent, skillCheck, skillSession } from "@/test-utils/skill-improvement";
import type { SkillContinuationEstimate, SkillImprovement } from "@/types/skill-improvement";
import type { MergeKind } from "@/types/skill-merge";
import { SkillImprovementPage } from "./skill-improvement-page";

const state = vi.hoisted(() => ({
  step: null as string | null,
  session: null as unknown,
  unresolved: 0,
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
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));
vi.mock("@/hooks/use-organizations", async (original) => ({
  ...(await original<typeof import("@/hooks/use-organizations")>()),
  useOrganizationList: () => ({ data: [] }),
}));
vi.mock("./merge-changes", () => ({
  MergeChanges: ({ editable }: { editable: boolean }) => (
    <p>{editable ? "edit the merge" : "read the merge"}</p>
  ),
}));
vi.mock("./merge-start", () => ({
  MergeStart: ({ forkId, kind }: { forkId: string; kind: MergeKind }) => (
    <p>{`start ${kind} of ${forkId}`}</p>
  ),
}));
vi.mock("@/components/improvement/next-step", () => ({
  NextStep: ({
    detail,
    hint,
    blocked,
    body,
  }: {
    detail?: (quote: SkillContinuationEstimate) => ReactNode;
    hint?: string;
    blocked?: string;
    body?: Record<string, unknown>;
  }) => (
    <div>
      <p>{hint}</p>
      <p>{blocked}</p>
      <p>{`body ${JSON.stringify(body ?? null)}`}</p>
      {detail?.({
        mode: "next_step",
        number: 1,
        total_usd: "0.30",
        budget_usd: "1.00",
        affordable: true,
        candidate_hash: "h",
        main_alone_usd: "0.12",
      })}
    </div>
  ),
}));

function merging(purpose: "catch_up" | "to_main", overrides: Partial<SkillImprovement> = {}) {
  return skillSession({
    purpose,
    fork_id: purpose === "catch_up" ? "f1" : null,
    line_name: purpose === "catch_up" ? "returns" : "main",
    merge_id: "m1",
    status: "waiting",
    stage: "filtering",
    check: null,
    outcomes: [],
    ...overrides,
  });
}

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
        can_edit: true,
        visibility: "org",
        owner_user_id: null,
      };
    if (path === "/skills/k1/improvements/s1") return state.session;
    if (path === "/skills/k1/improvements/s1/merge")
      return { id: "m1", unresolved: state.unresolved };
    throw new ApiError(404, "None");
  });
}

function mount(
  props: { sessionId?: string; forkId?: string | null; merge?: MergeKind | null } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <SkillImprovementPage
      skillId="k1"
      sessionId={props.sessionId ?? "s1"}
      forkId={props.forkId ?? null}
      merge={props.merge ?? null}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  state.step = null;
  state.unresolved = 0;
  state.session = merging("catch_up");
  serve();
});

describe("a session merging a fork with main", () => {
  it("starts a catch-up of the fork the address names", async () => {
    mount({ sessionId: "new", forkId: "f1", merge: "catch_up" });
    expect(await screen.findByText("start catch_up of f1")).toBeVisible();
  });

  it("holds the check until the merge is settled, and asks about main alone", async () => {
    state.unresolved = 2;
    mount();

    expect(await screen.findByText("edit the merge")).toBeVisible();
    expect(
      screen.getByText(
        "Check the merged skill on the fork's agents before it becomes the fork's next version.",
      ),
    ).toBeVisible();
    expect(await screen.findByText("Settle the 2 open parts first.")).toBeVisible();
    expect(screen.getByText('body {"main_alone":true}')).toBeVisible();

    const alone = screen.getByRole("checkbox", {
      name: /Also check main's newest version alone on the fork's agents \(\+\$0\.12\)/,
    });
    await userEvent.click(alone);
    expect(screen.getByText('body {"main_alone":false}')).toBeVisible();
  });

  it("checks a move to main on main's agents, with nothing more to ask", async () => {
    state.session = merging("to_main");
    mount();

    expect(
      await screen.findByText(
        "Check the merged skill on main's agents before it becomes main's next version.",
      ),
    ).toBeVisible();
    await waitFor(() => expect(screen.getByText("body null")).toBeVisible());
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("says the assistant is writing the conflicts' texts while it does", async () => {
    state.session = merging("catch_up", { status: "running", stage: "proposing" });
    mount();

    expect(
      await screen.findByText("The assistant is writing a combined text for each conflict."),
    ).toBeVisible();
  });

  it("shows the merge it checked once the check runs, read-only", async () => {
    state.session = merging("catch_up", {
      status: "running",
      stage: "evaluating",
      check: skillCheck({ verdict: null, agents: [checkAgent("Support", "running")] }),
    });
    state.step = "changes";
    mount();

    expect(await screen.findByText("read the merge")).toBeVisible();
  });

  it("says why main alone was not checked beside the result", async () => {
    state.session = merging("catch_up", {
      status: "ready",
      stage: "judging",
      check: skillCheck(),
      main_alone: "off",
      outcomes: ["catch_up", "discard"],
    });
    state.step = "result";
    mount();

    expect(
      await screen.findByText(
        "Main alone was not checked, so returning the fork's agents to main is not offered.",
      ),
    ).toBeVisible();
  });
});
