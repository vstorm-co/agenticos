import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { evalSuite, suiteResult, suiteSummary } from "@/test-utils/eval-suites";
import type { EvalSuite, EvalSuiteResult } from "@/types/eval-suites";
import { Perm, type Permission } from "@/types/permissions";
import { EvalSuitesCard } from "./eval-suites-card";
import { formFor, inputFor } from "./suite-form-dialog";

interface Mutation {
  data?: unknown;
  error: unknown;
  isPending: boolean;
  mutate: ReturnType<typeof vi.fn>;
  mutateAsync: ReturnType<typeof vi.fn>;
}

function mutation(overrides: Partial<Mutation> = {}): Mutation {
  return {
    data: undefined,
    error: null,
    isPending: false,
    mutate: vi.fn(),
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

const hooks = vi.hoisted(() => ({
  suites: [] as unknown[],
  isPending: false,
  error: null as unknown,
  refetch: (() => undefined) as () => unknown,
  create: undefined as unknown,
  update: undefined as unknown,
  setActive: undefined as unknown,
  runNow: undefined as unknown,
  remove: undefined as unknown,
  estimate: undefined as unknown,
  results: [] as unknown[],
  resultsLoading: false,
  resultsError: null as unknown,
  total: 0,
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useEvalSuites: () => ({
    suites: hooks.suites,
    isPending: hooks.isPending,
    error: hooks.error,
    refetch: hooks.refetch,
    create: hooks.create,
    update: hooks.update,
    setActive: hooks.setActive,
    runNow: hooks.runNow,
    remove: hooks.remove,
    estimate: hooks.estimate,
  }),
  useEvalSuiteResults: () => ({
    results: hooks.results,
    total: hooks.total,
    isLoading: hooks.resultsLoading,
    error: hooks.resultsError,
  }),
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEveryDataset: () => ({
    datasets: [
      { id: "dataset-1", name: "refunds", case_count: 4 },
      { id: "dataset-2", name: "empty", case_count: 0 },
    ],
  }),
}));
vi.mock("@/hooks/use-agent-environments", () => ({
  useAgentEnvironments: () => ({ environments: [{ id: "env-1", name: "staging" }] }),
}));
const access = vi.hoisted(() => ({ allowed: new Set<string>(), org: "org-1" as string | null }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => access.allowed.has(permission) }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (state: { activeOrgId: string | null }) => unknown) =>
    select({ activeOrgId: access.org }),
}));

const ESTIMATE = {
  cases: 4,
  arms: [],
  judge_usd: "0",
  judge_model_profile_id: null,
  total_usd: "0.20",
  rerun_ceiling_usd: "0.10",
  agent_remaining_usd: null,
  org_remaining_usd: null,
  agent_after_usd: null,
  org_after_usd: null,
  affordable: true,
};

beforeEach(() => {
  hooks.suites = [];
  hooks.isPending = false;
  hooks.error = null;
  hooks.refetch = vi.fn();
  hooks.create = mutation();
  hooks.update = mutation();
  hooks.setActive = mutation();
  hooks.runNow = mutation();
  hooks.remove = mutation();
  hooks.estimate = mutation();
  hooks.results = [];
  hooks.resultsLoading = false;
  hooks.resultsError = null;
  hooks.total = 0;
  access.allowed = new Set();
  access.org = "org-1";
});

function card(suites: EvalSuite[], canManage = true) {
  hooks.suites = suites;
  return render(<EvalSuitesCard agentId="agent-1" canManage={canManage} />);
}

describe("EvalSuitesCard", () => {
  it("says in one line that there is none, and offers one to whoever may", async () => {
    card([]);
    expect(screen.getByText(/^No suites yet/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New suite" })).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "New suite" }));
    expect(screen.getByRole("dialog", { name: "New suite" })).toBeInTheDocument();
  });

  it("offers no suite to whoever may not save one", () => {
    card([], false);
    expect(screen.getByText(/^No suites yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New suite" })).toBeNull();
  });

  it("offers nothing to change to whoever may not", () => {
    card([evalSuite()], false);
    expect(screen.queryByRole("button", { name: "New suite" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run now" })).toBeNull();
  });

  it("holds a skeleton until the suites are read, and says when they could not be", async () => {
    hooks.isPending = true;
    const { rerender } = card([]);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText(/^No suites yet/)).toBeNull();

    hooks.isPending = false;
    hooks.error = new Error("boom");
    rerender(<EvalSuitesCard agentId="agent-1" canManage />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(hooks.refetch).toHaveBeenCalled();
  });

  it("shows each suite's dataset, when it runs and how it last came out", () => {
    card([
      evalSuite(),
      evalSuite({
        id: "suite-2",
        name: "On publish",
        dataset_name: null,
        environment_name: "staging",
        schedule: null,
        on_publish: false,
        is_active: false,
        paused_reason: "owner_inactive",
        last_result: suiteResult({ status: "skipped", reason: "budget" }),
      }),
      evalSuite({
        id: "suite-3",
        name: "Weekly",
        dataset_name: "faq",
        on_dependency_change: true,
        is_active: false,
        last_result: null,
        open_result: suiteResult({ status: "running", settled_at: null }),
      }),
    ]);
    expect(screen.getByText("refunds · current published version")).toBeInTheDocument();
    expect(screen.getByText("Daily at 06:00 (Europe/Warsaw) · On publish")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Daily at 06:00 (Europe/Warsaw) · On publish · When a skill or knowledge base changes",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Passed · 100%")).toBeInTheDocument();
    expect(screen.getByText("a dataset you cannot see · staging")).toBeInTheDocument();
    expect(screen.getByText("Only when run by hand")).toBeInTheDocument();
    expect(screen.getByText("Did not run")).toBeInTheDocument();
    expect(screen.getByText("Paused: its owner left")).toBeInTheDocument();
    expect(screen.getByText("Paused")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/^Next /)).toBeInTheDocument();
  });

  it("shows what each suite's results must meet", () => {
    card([
      evalSuite({
        threshold: {
          min_pass_rate: 0.7,
          max_confirmed_regressions: 0,
          max_cost_per_pass_rise: null,
          max_p95_rise: null,
        },
      }),
      evalSuite({ id: "suite-2", name: "Lenient" }),
    ]);
    expect(screen.getByText("≥70% · 0 regressions")).toHaveAttribute("title", "Threshold");
    expect(screen.getByText("0 regressions")).toBeInTheDocument();
  });

  it("runs, pauses, resumes and deletes a suite from its row", async () => {
    const runNow = mutation({
      mutate: vi.fn((_id: string, options?: { onSuccess?: () => void }) => options?.onSuccess?.()),
    });
    hooks.runNow = runNow;
    card([evalSuite(), evalSuite({ id: "suite-2", name: "Paused", is_active: false })]);
    const [first, second] = screen.getAllByRole("button", { name: "Run now" });

    await userEvent.click(first!);
    expect(runNow.mutate).toHaveBeenCalledWith("suite-1", expect.anything());
    expect(
      screen.getByText("No results yet. A result appears when the suite next runs."),
    ).toBeInTheDocument();
    expect(second).toBeDisabled();

    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getAllByRole("button", { name: "Pause" })[0]!);
    expect((hooks.setActive as Mutation).mutate).toHaveBeenCalledWith({
      suiteId: "suite-1",
      isActive: false,
    });
    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    expect((hooks.setActive as Mutation).mutate).toHaveBeenCalledWith({
      suiteId: "suite-2",
      isActive: true,
    });

    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]!);
    const confirm = screen.getByRole("dialog", { name: "Delete this suite?" });
    await userEvent.click(within(confirm).getByRole("button", { name: "Delete" }));
    expect((hooks.remove as Mutation).mutate).toHaveBeenCalledWith("suite-1");
  });
});

describe("SuiteResultsSheet", () => {
  async function open(results: EvalSuiteResult[]) {
    hooks.results = results;
    hooks.total = results.length;
    card([evalSuite()]);
    await userEvent.click(screen.getByRole("button", { name: "Results of Nightly" }));
  }

  it("lists each result: how it came out, why, which cases broke, and its run", async () => {
    access.allowed = new Set([Perm.orgSettings]);
    await open([
      suiteResult({
        id: "r1",
        status: "failed",
        summary: suiteSummary({
          pass_rate: 0.5,
          regressions_confirmed: 1,
          reasons: [{ code: "regressions", value: 1, limit: 0, detail: null }],
          failing_cases: [
            { case_id: "c1", input: "Can I return it?", kind: "regression" },
            { case_id: "c2", input: "Where is it?", kind: "failed" },
            { case_id: "c3", input: "Who decides?", kind: "ungraded" },
          ],
        }),
      }),
      suiteResult({
        id: "r2",
        status: "skipped",
        reason: "ai_assistance_off",
        eval_run_id: null,
        summary: null,
        trigger: "publish",
      }),
      suiteResult({ id: "r3", status: "error", reason: null, summary: null, settled_at: null }),
      suiteResult({ id: "r4", status: "running", summary: null, version_number: null }),
      suiteResult({ id: "r5", status: "inconclusive", summary: null }),
      suiteResult({ id: "r6", status: "inconclusive", reason: "cancelled", summary: null }),
    ]);

    const sheet = screen.getByRole("dialog");
    expect(within(sheet).getByText("Failed")).toBeInTheDocument();
    expect(
      within(sheet).getByText("1 case breaks reproducibly; the suite allows 0."),
    ).toBeInTheDocument();
    expect(within(sheet).getByText("Breaks reproducibly: Can I return it?")).toBeInTheDocument();
    expect(within(sheet).getByText("Failed: Where is it?")).toBeInTheDocument();
    expect(within(sheet).getByText("Not graded: Who decides?")).toBeInTheDocument();
    expect(
      within(sheet).getByText(/Pass rate 50% over 4 cases · 1 confirmed regression/),
    ).toBeInTheDocument();
    expect(
      within(sheet).getByText("Only the judge could grade these cases, and AI assistance is off."),
    ).toBeInTheDocument();
    expect(within(sheet).getByText("Its eval run was stopped.")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Turn on AI assistance" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members",
    );
    expect(within(sheet).getAllByRole("link", { name: /Open run/ })[0]).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-1",
    );

    expect(within(sheet).getAllByText(/ · v3 · /).length).toBeGreaterThan(0);
    expect(within(sheet).queryByText(/v0/)).toBeNull();

    await userEvent.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("waits, says when the results could not be read, and when there are none", async () => {
    hooks.resultsLoading = true;
    await open([]);
    expect(screen.queryByText(/No results yet/)).toBeNull();
    await userEvent.keyboard("{Escape}");

    hooks.resultsLoading = false;
    hooks.resultsError = new Error("boom");
    await userEvent.click(screen.getByRole("button", { name: "Results of Nightly" }));
    expect(screen.getByText("The results could not be read.")).toBeInTheDocument();
  });
});

describe("SuiteFormDialog", () => {
  async function openNew() {
    card([]);
    await userEvent.click(screen.getByRole("button", { name: "New suite" }));
    return screen.getByRole("dialog", { name: "New suite" });
  }

  it("prices the suite once a dataset is chosen, and saves it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    hooks.estimate = mutation({
      data: { run: ESTIMATE, paired_run: ESTIMATE, fires_per_month: 30, monthly_usd: "6.00" },
    });
    const dialog = await openNew();
    expect(within(dialog).getByRole("button", { name: "Create suite" })).toBeDisabled();

    await userEvent.type(within(dialog).getByLabelText("Name"), "Nightly");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "refunds · 4 cases" }));
    await userEvent.click(within(dialog).getByLabelText("On a schedule"));
    await act(() => vi.advanceTimersByTimeAsync(500));

    expect((hooks.estimate as Mutation).mutate).toHaveBeenCalledWith({
      dataset_id: "dataset-1",
      environment_id: null,
      schedule: { cron: "0 6 * * *", timezone: expect.any(String) },
    });
    expect(within(dialog).getByText("One run: about $0.20 for 4 cases.")).toBeInTheDocument();
    expect(within(dialog).getByText(/previous version runs beside it/)).toBeInTheDocument();
    expect(
      within(dialog).getByText("The schedule: 30 runs in 30 days, about $6.00."),
    ).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));
    expect((hooks.create as Mutation).mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Nightly", dataset_id: "dataset-1", on_publish: true }),
    );
    vi.useRealTimers();
  });

  it("offers a weekday, a custom cron and the folded efficiency settings", async () => {
    const dialog = await openNew();
    await userEvent.click(within(dialog).getByLabelText("On a schedule"));
    await userEvent.clear(within(dialog).getByLabelText("At"));
    await userEvent.type(within(dialog).getByLabelText("At"), "07:30");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Repeats" }));
    await userEvent.click(screen.getByRole("option", { name: "Once a week" }));
    await userEvent.click(within(dialog).getByRole("combobox", { name: "On" }));
    await userEvent.click(screen.getByRole("option", { name: "Wed" }));
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Repeats" }));
    await userEvent.click(screen.getByRole("option", { name: "Custom (cron)" }));
    await userEvent.clear(within(dialog).getByLabelText("Cron expression"));
    await userEvent.type(within(dialog).getByLabelText("Cron expression"), "0 7 1 * *");
    await userEvent.clear(within(dialog).getByLabelText("Time zone"));
    await userEvent.type(within(dialog).getByLabelText("Time zone"), "UTC");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Version checked" }));
    await userEvent.click(screen.getByRole("option", { name: "staging" }));
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Version checked" }));
    await userEvent.click(screen.getByRole("option", { name: "Current published version" }));
    for (const label of [
      "On every publish",
      "On promotion",
      "When a skill or knowledge base changes",
    ]) {
      await userEvent.click(within(dialog).getByLabelText(label));
    }
    await userEvent.clear(within(dialog).getByLabelText("Confirmed regressions allowed"));
    await userEvent.type(within(dialog).getByLabelText("Confirmed regressions allowed"), "1");
    await userEvent.type(within(dialog).getByLabelText("Minimum pass rate (%)"), "80");
    await userEvent.click(within(dialog).getByRole("button", { name: "Efficiency and spend" }));
    await userEvent.type(
      within(dialog).getByLabelText("Cost per passed case may rise by (%)"),
      "20",
    );
    await userEvent.type(within(dialog).getByLabelText("p95 latency may rise by (%)"), "50");
    await userEvent.type(within(dialog).getByLabelText("Skip a run estimated above ($)"), "2");
    await userEvent.type(within(dialog).getByLabelText("Note"), "Checked weekly");
    await userEvent.type(within(dialog).getByLabelText("Name"), "Weekly");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "refunds · 4 cases" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));

    expect((hooks.create as Mutation).mutateAsync).toHaveBeenCalledWith({
      name: "Weekly",
      description: "Checked weekly",
      dataset_id: "dataset-1",
      environment_id: null,
      threshold: {
        min_pass_rate: 0.8,
        max_confirmed_regressions: 1,
        max_cost_per_pass_rise: 0.2,
        max_p95_rise: 0.5,
      },
      on_publish: false,
      on_promotion: true,
      on_dependency_change: true,
      schedule: { cron: "0 7 1 * *", timezone: "UTC" },
      max_run_usd: "2",
    });
  });

  it("edits a suite as it is, saves it, and shows a refusal with where to fix it", async () => {
    access.allowed = new Set([Perm.orgSettings]);
    hooks.update = mutation({
      error: new ApiError(400, "off", {
        error: { code: "BAD_REQUEST", message: "off", details: { reason: "ai_assistance_off" } },
      }),
    });
    card([evalSuite({ schedule: { cron: "0 6 * * 2", timezone: "UTC" } })]);
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog", { name: "Edit suite" });

    expect(within(dialog).getByLabelText("Name")).toHaveValue("Nightly");
    expect(within(dialog).getByRole("link", { name: "Turn on AI assistance" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect((hooks.update as Mutation).mutateAsync).toHaveBeenCalledWith({
      suiteId: "suite-1",
      input: expect.objectContaining({ schedule: { cron: "0 6 * * 2", timezone: "UTC" } }),
    });

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Edit suite" })).toBeNull();
  });

  it("keeps the dialog open when saving is refused", async () => {
    hooks.create = mutation({ mutateAsync: vi.fn().mockRejectedValue(new Error("taken")) });
    const dialog = await openNew();
    await userEvent.type(within(dialog).getByLabelText("Name"), "Nightly");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "refunds · 4 cases" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create suite" }));

    expect(screen.getByRole("dialog", { name: "New suite" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "New suite" })).toBeNull();
  });
});

describe("formFor and inputFor", () => {
  it("round-trip a suite's settings", () => {
    const suite = evalSuite({
      description: "Nightly",
      threshold: {
        min_pass_rate: 0.8,
        max_confirmed_regressions: 2,
        max_cost_per_pass_rise: 0.25,
        max_p95_rise: 1,
      },
      max_run_usd: "1.50",
    });
    expect(inputFor(formFor(suite))).toEqual({
      name: "Nightly",
      description: "Nightly",
      dataset_id: "dataset-1",
      environment_id: null,
      threshold: suite.threshold,
      on_publish: true,
      on_promotion: false,
      on_dependency_change: false,
      schedule: { cron: "0 6 * * *", timezone: "Europe/Warsaw" },
      max_run_usd: "1.50",
    });
  });

  it("start a new suite on publish, unscheduled, in the reader's zone", () => {
    const form = formFor(undefined);
    expect(form).toMatchObject({ onPublish: true, scheduled: false, maxRegressions: "0" });
    expect(form.timezone).not.toBe("");
    expect(inputFor({ ...form, maxRegressions: "" }).threshold.max_confirmed_regressions).toBe(0);
  });
});
