import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { ESTIMATE, evalRun } from "@/test-utils/eval-runs";
import type { EvalRunRequest } from "@/types/eval-runs";
import { Perm, type Permission } from "@/types/permissions";
import { StartEvalDialog } from "./start-eval-dialog";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

interface Mutation {
  data?: unknown;
  variables?: unknown;
  error: unknown;
  isPending: boolean;
  mutate: ReturnType<typeof vi.fn>;
  mutateAsync: ReturnType<typeof vi.fn>;
  reset: ReturnType<typeof vi.fn>;
}

function mutation(overrides: Partial<Mutation> = {}): Mutation {
  return {
    data: undefined,
    variables: undefined,
    error: null,
    isPending: false,
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

const access = vi.hoisted(() => ({
  allowed: new Set<string>(),
  org: "org-1" as string | null,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: Permission) => access.allowed.has(permission) }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (state: { activeOrgId: string | null }) => unknown) =>
    select({ activeOrgId: access.org }),
}));

const DRAFT = { instructions: "Answer refunds kindly." };
const AGENTS = [
  { id: "agent-1", slug: "refund-desk", name: "Refund desk", can_run: true, kind: "agent" },
  { id: "agent-2", slug: "shipping-desk", name: "Shipping desk", can_run: true, kind: "agent" },
  { id: "judge", slug: "judge", name: "Eval judge", can_run: true, kind: "judge" },
  { id: "locked", slug: "payroll", name: "Payroll", can_run: false, kind: "agent" },
];
const agentList = vi.hoisted(() => ({ items: [] as unknown[], error: null as Error | null }));
const agentState = vi.hoisted(() => ({
  currentVersionId: "v7" as string | null,
  liveSpec: {} as Record<string, unknown>,
  canEdit: true,
  loading: false,
  error: null as Error | null,
}));
vi.mock("@/hooks", () => ({
  useAgent: (id: string | null) => ({
    isLoading: agentState.loading,
    error: agentState.error,
    agent:
      id === null
        ? undefined
        : {
            id,
            current_version_id: agentState.currentVersionId,
            draft_spec: DRAFT,
            can_edit: agentState.canEdit,
          },
  }),
  useAgentVersion: (_: string | null, versionId: string | null) => ({
    version: versionId === null ? undefined : { version: 7, spec: agentState.liveSpec },
  }),
}));

const datasets = vi.hoisted(() => ({
  items: [] as unknown[],
  error: null as Error | null,
  loading: false,
}));
const hooks = vi.hoisted(() => ({
  estimate: undefined as unknown,
  start: undefined as unknown,
  runs: [] as unknown[],
  datasetRuns: [] as unknown[],
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRuns: () => ({ runs: hooks.runs, estimate: hooks.estimate, start: hooks.start }),
  useDatasetEvalRuns: () => ({ runs: hooks.datasetRuns }),
  useEveryAgent: () => ({ agents: agentList.items, error: agentList.error }),
  useEveryDataset: () => ({
    datasets: datasets.items,
    error: datasets.error,
    isLoading: datasets.loading,
  }),
}));
vi.mock("@/hooks/use-agent-environments", () => ({
  useAgentEnvironments: () => ({ environments: [{ id: "env-1", name: "staging" }] }),
}));

const SCORING = {
  checks: { enabled: true, required: false, defaults: [] },
  trajectory: { enabled: false, required: false },
  judge: {
    enabled: true,
    agent_id: null,
    model_profile_id: null,
    scale_max: 5,
    pass_at: 4,
    criteria: [],
  },
  reference: { enabled: false, required: false },
  review: { select: "none" },
};
const REFUNDS = {
  id: "ds-1",
  name: "refunds",
  case_count: 20,
  latest_version: 3,
  can_run: true,
  run_needs: [],
  scoring: SCORING,
  judge_name: "Policy judge",
};

/** The request the dialog asks for by default: the draft against v7, on refunds. */
const COMPARE: EvalRunRequest = {
  dataset_id: "ds-1",
  candidate: "draft",
  model_profile_ids: [],
  paired_baseline: true,
  from_recordings: false,
  live_reads: false,
};

function open(props: Partial<Parameters<typeof StartEvalDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  render(<StartEvalDialog agentId="agent-1" onOpenChange={onOpenChange} {...props} />);
  return onOpenChange;
}

async function choose(combobox: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: combobox }));
  await userEvent.click(screen.getByRole("option", { name: option }));
}

const estimated = () => (hooks.estimate as Mutation).mutate;

beforeEach(() => {
  vi.clearAllMocks();
  access.allowed = new Set([Perm.agentsEdit]);
  access.org = "org-1";
  agentState.currentVersionId = "v7";
  agentState.canEdit = true;
  agentState.loading = false;
  agentState.error = null;
  agentState.liveSpec = { instructions: "Answer refunds." };
  datasets.error = null;
  datasets.loading = false;
  agentList.error = null;
  datasets.items = [
    REFUNDS,
    { id: "ds-2", name: "empty", case_count: 0, latest_version: 0, can_run: true },
  ];
  hooks.runs = [];
  hooks.datasetRuns = [];
  agentList.items = [...AGENTS];
  hooks.estimate = mutation();
  hooks.start = mutation();
});

describe("StartEvalDialog", () => {
  it.each(["agents", "datasets"])(
    "blocks an incomplete %s listing and reports the failure",
    (kind) => {
      agentList.items = [AGENTS[0]];
      if (kind === "agents") agentList.error = new Error("Listing unavailable");
      else datasets.error = new Error("Listing unavailable");
      open({ agentId: null });
      expect(screen.getByRole("alert")).toHaveTextContent("Listing unavailable");
      expect(screen.getByRole("button", { name: "Run evals" })).toBeDisabled();
      expect(estimated()).not.toHaveBeenCalled();
    },
  );
  it("keeps dataset loading separate from having no datasets", () => {
    datasets.loading = true;
    open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toBeDisabled();
    expect(screen.queryByText("There are no datasets you can run.")).toBeNull();
    expect(screen.getByRole("button", { name: "Run evals" })).toBeDisabled();
  });

  it("shows loading rather than a missing-version refusal while reading the selected agent", () => {
    agentState.loading = true;
    open();
    expect(screen.getByRole("status")).toHaveTextContent(/Loading/);
    expect(screen.queryByText(/This agent has no published version/)).toBeNull();
  });

  it("shows a failed agent read rather than offering unavailable targets", () => {
    agentState.error = new Error("Agent unavailable");
    open();
    expect(screen.getByRole("alert")).toHaveTextContent("Agent unavailable");
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("tests a changed draft against what is live, on the only dataset, priced as it settles", async () => {
    open();

    expect(screen.getByRole("radio", { name: /The draft against v7/ })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent(
      "refunds · 20 cases · v3",
    );
    expect(screen.getByRole("button", { name: "Estimating…" })).toBeDisabled();
    await waitFor(() => expect(estimated()).toHaveBeenCalledWith(COMPARE));
  });

  it("measures what is live when the draft has not changed", async () => {
    agentState.liveSpec = DRAFT;
    open();

    expect(screen.getByRole("radio", { name: /v7 alone/ })).toBeChecked();
    await waitFor(() =>
      expect(estimated()).toHaveBeenCalledWith({
        ...COMPARE,
        candidate: "version",
        paired_baseline: false,
      }),
    );
  });

  it("says when no earlier run compares, and offers to run the version before beside it", async () => {
    agentState.liveSpec = DRAFT;
    const alone = { ...COMPARE, candidate: "version" as const, paired_baseline: false };
    hooks.estimate = mutation({
      data: { ...ESTIMATE, missing_baseline_version: 6 },
      variables: alone,
    });
    open();

    expect(screen.getByText(/No comparable earlier run/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Also run the version before it"));

    await waitFor(() =>
      expect(estimated()).toHaveBeenCalledWith({ ...alone, paired_baseline: true }),
    );
    expect(screen.queryByText(/No comparable earlier run/)).toBeNull();
  });

  it("asks again for what was chosen, the advanced fields included", async () => {
    open();
    await userEvent.click(screen.getByRole("radio", { name: /v7 alone/ }));
    await userEvent.click(screen.getByText("Advanced"));
    await choose("Environment", "staging");
    await userEvent.click(screen.getByLabelText(/Replay tool results/));
    await choose("Confirming reruns", "1 rerun");

    await waitFor(() =>
      expect(estimated()).toHaveBeenLastCalledWith(
        expect.objectContaining({
          candidate: "version",
          paired_baseline: false,
          environment_id: "env-1",
          from_recordings: true,
          reruns: 1,
        }),
      ),
    );
    // Every change clears the price on screen, so nothing stale is agreed to.
    expect((hooks.estimate as Mutation).reset).toHaveBeenCalled();

    await choose("Confirming reruns", "Default");
    await choose("Environment", "None");
    await waitFor(() =>
      expect(estimated()).toHaveBeenLastCalledWith(
        expect.objectContaining({ environment_id: null, reruns: null }),
      ),
    );
  });

  it("tests the draft alone for an agent nobody published", async () => {
    agentState.currentVersionId = null;
    open();

    expect(screen.getAllByRole("radio")).toHaveLength(1);
    expect(screen.getByRole("radio", { name: /The draft/ })).toBeChecked();
    expect(screen.getByText(/this is the first result/)).toBeInTheDocument();
    await waitFor(() =>
      expect(estimated()).toHaveBeenCalledWith({ ...COMPARE, paired_baseline: false }),
    );
  });

  it("offers only what is live to a caller who may not edit the draft", () => {
    // The role may edit agents, but not this one: the agent's own answer decides.
    agentState.canEdit = false;
    open();
    expect(screen.getAllByRole("radio")).toHaveLength(1);
    expect(screen.getByRole("radio", { name: /v7 alone/ })).toBeChecked();
  });

  it("says when there is nothing the caller may test, and prices nothing", async () => {
    agentState.canEdit = false;
    agentState.currentVersionId = null;
    open();

    expect(screen.getByText(/no published version/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run evals" })).toBeDisabled();
    await new Promise((resolve) => setTimeout(resolve, 450));
    expect(estimated()).not.toHaveBeenCalled();
  });

  it("keeps an empty dataset named, explains the missing cases and never estimates it", async () => {
    const close = open({ datasetId: "ds-2" });
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("empty");
    expect(screen.getByText(/This dataset has no cases yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open cases" })).toHaveAttribute(
      "href",
      "/datasets/ds-2?tab=cases",
    );
    expect(screen.getByRole("button", { name: "Run evals" })).toBeDisabled();
    await userEvent.click(screen.getByRole("link", { name: "Open cases" }));
    expect(close).toHaveBeenCalledWith(false);
    await choose("Dataset", "refunds · 20 cases · v3");
    await waitFor(() => expect(estimated()).toHaveBeenCalledWith(COMPARE));
  });

  it("explains when no dataset can be run instead of opening an empty menu", () => {
    datasets.items = [];
    open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toBeDisabled();
    expect(screen.getByText("There are no datasets you can run.")).toBeInTheDocument();
  });

  it("asks for a fresh price when the agent changes but the eval choices stay identical", async () => {
    open({ agentId: null, datasetId: "ds-1" });
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Refund desk" }));
    await waitFor(() => expect(estimated()).toHaveBeenCalledWith(COMPARE));
    estimated().mockClear();
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Shipping desk" }));
    await waitFor(() => expect(estimated()).toHaveBeenCalledWith(COMPARE));
  });

  it("offers the dataset this agent was last measured on", async () => {
    datasets.items = [
      REFUNDS,
      { ...REFUNDS, id: "ds-3", name: "shipping", case_count: 4, latest_version: 1 },
    ];
    hooks.runs = [evalRun({ dataset_id: "ds-3" })];
    open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("shipping");

    hooks.runs = [];
    await choose("Dataset", "refunds · 20 cases · v3");
    await waitFor(() => expect(estimated()).toHaveBeenLastCalledWith(COMPARE));
  });

  it("offers no dataset the caller may only read", async () => {
    datasets.items = [REFUNDS, { ...REFUNDS, id: "ds-3", name: "shipping", can_run: false }];
    open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("refunds");
    await userEvent.click(screen.getByRole("combobox", { name: "Dataset" }));
    expect(screen.queryByRole("option", { name: /shipping/ })).toBeNull();
  });

  it("offers nothing to run when there is more than one dataset and no history", () => {
    datasets.items = [REFUNDS, { ...REFUNDS, id: "ds-3", name: "shipping" }];
    open();
    expect(screen.getByRole("combobox", { name: "Dataset" })).toHaveTextContent("Choose a dataset");
    expect(screen.getByRole("button", { name: "Run evals" })).toBeDisabled();
  });

  it("chooses the agent when the run starts from a dataset", async () => {
    open({ agentId: null, datasetId: "ds-1" });
    expect(screen.queryByRole("radio")).toBeNull();

    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    expect(screen.queryByRole("option", { name: "Eval judge" })).toBeNull();
    expect(screen.queryByRole("option", { name: "Payroll" })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "Refund desk" }));

    expect(screen.getByRole("radio", { name: /The draft against v7/ })).toBeChecked();
    await waitFor(() => expect(estimated()).toHaveBeenCalledWith(COMPARE));
  });

  it("drops the environment picked for one agent when another is chosen", async () => {
    open({ agentId: null, datasetId: "ds-1" });
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Refund desk" }));
    await userEvent.click(screen.getByText("Advanced"));
    await choose("Environment", "staging");
    await waitFor(() =>
      expect(estimated()).toHaveBeenLastCalledWith(
        expect.objectContaining({ environment_id: "env-1" }),
      ),
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Shipping desk" }));
    await waitFor(() =>
      expect(estimated()).toHaveBeenLastCalledWith(
        expect.not.objectContaining({ environment_id: "env-1" }),
      ),
    );
  });

  it("offers the agent last measured on the dataset it starts from", () => {
    hooks.datasetRuns = [evalRun({ agent_id: "judge" }), evalRun({ agent_id: "agent-2" })];
    open({ agentId: null, datasetId: "ds-1" });
    expect(screen.getByRole("combobox", { name: "Agent" })).toHaveTextContent("Shipping desk");
    expect(screen.getByRole("radio", { name: /The draft against v7/ })).toBeChecked();
  });

  it("offers the only agent there is to test", () => {
    agentList.items = AGENTS.filter((agent) => agent.id !== "agent-2");
    open({ agentId: null, datasetId: "ds-1" });
    expect(screen.getByRole("combobox", { name: "Agent" })).toHaveTextContent("Refund desk");
  });

  it("opens on an available target the caller asked to test", () => {
    open({ target: "version" });
    expect(screen.getByRole("radio", { name: /v7 alone/ })).toBeChecked();
  });

  it("runs what was priced, says what grades it, and opens the run", async () => {
    hooks.estimate = mutation({ data: ESTIMATE, variables: COMPARE });
    hooks.start = mutation({ mutateAsync: vi.fn().mockResolvedValue(evalRun()) });
    const onOpenChange = open();

    expect(screen.getByText("Graded by checks and Policy judge.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run for $0.30" }));

    expect((hooks.start as Mutation).mutateAsync).toHaveBeenCalledWith(COMPARE);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(push).toHaveBeenCalledWith("/agents/agent-1/evals/run-1");
  });

  it("warns before the run that a case nothing grades leaves the result inconclusive", () => {
    hooks.estimate = mutation({ data: { ...ESTIMATE, ungraded_cases: 1 }, variables: COMPARE });
    open();
    expect(
      screen.getByText("1 case has nothing to grade it. The result will be inconclusive."),
    ).toBeInTheDocument();
  });

  it("shows no price that was asked for other fields", () => {
    hooks.estimate = mutation({ data: ESTIMATE, variables: { ...COMPARE, reruns: 3 } });
    open();
    expect(screen.queryByRole("button", { name: "Run for $0.30" })).toBeNull();
  });

  it("refuses to run what the budget cannot hold, and says why the server refused", async () => {
    hooks.estimate = mutation({ data: { ...ESTIMATE, affordable: false }, variables: COMPARE });
    hooks.start = mutation({
      error: new Error("This eval would cost more than is left"),
      mutateAsync: vi.fn().mockRejectedValue(new Error("refused")),
    });
    const onOpenChange = open();

    expect(screen.getByRole("button", { name: "Run for $0.30" })).toBeDisabled();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("stays open when the server refuses the start", async () => {
    hooks.estimate = mutation({ data: ESTIMATE, variables: COMPARE });
    hooks.start = mutation({ mutateAsync: vi.fn().mockRejectedValue(new Error("402")) });
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Run for $0.30" }));

    expect(onOpenChange).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("explains each invalid draft field and closes when returning to Build", async () => {
    hooks.estimate = mutation({
      error: new ApiError(400, "The draft cannot be evaluated", {
        error: {
          code: "BAD_REQUEST",
          message: "The draft cannot be evaluated",
          details: { problems: ["Choose a model"] },
        },
      }),
    });
    const onOpenChange = open();
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a model");
    expect(screen.getByRole("link", { name: "Back to Build" })).toHaveAttribute(
      "href",
      "/agents/agent-1?tab=build",
    );
    expect(onOpenChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("link", { name: "Back to Build" }));
    expect(onOpenChange).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("shows whoever may turn AI assistance on where to do it", () => {
    const off = new ApiError(400, "The judge needs AI assistance", {
      error: {
        code: "BAD_REQUEST",
        message: "The judge needs AI assistance, which is off for this organization",
        details: { reason: "ai_assistance_off" },
      },
    });
    hooks.estimate = mutation({ error: off });
    access.allowed = new Set([Perm.agentsEdit, Perm.orgSettings]);
    open();
    expect(screen.getByRole("link", { name: "Open the organization's settings" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members",
    );
    expect(screen.getByRole("button", { name: "Run evals" })).toBeDisabled();
  });

  it("shows no settings link to who cannot change them, or for another refusal", () => {
    const off = new ApiError(400, "off", {
      error: { code: "BAD_REQUEST", message: "off", details: { reason: "ai_assistance_off" } },
    });
    hooks.estimate = mutation({ error: off });
    open();
    expect(screen.queryByRole("link", { name: /organization's settings/ })).toBeNull();
  });
});

it("disables comparison when the draft matches the published version", () => {
  agentState.liveSpec = DRAFT;
  render(<StartEvalDialog agentId="agent-1" target="compare" onOpenChange={vi.fn()} />);
  expect(screen.getByRole("radio", { name: /No changes/ })).toBeDisabled();
  expect(screen.getByRole("radio", { name: /How the version people/ })).toBeChecked();
});
