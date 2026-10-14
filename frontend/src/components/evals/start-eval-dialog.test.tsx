import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { ESTIMATE, evalRun } from "@/test-utils/eval-runs";
import { StartEvalDialog } from "./start-eval-dialog";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

interface Mutation {
  data?: unknown;
  error: unknown;
  isPending: boolean;
  mutate: ReturnType<typeof vi.fn>;
  mutateAsync: ReturnType<typeof vi.fn>;
  reset: ReturnType<typeof vi.fn>;
}

function mutation(overrides: Partial<Mutation> = {}): Mutation {
  return {
    data: undefined,
    error: null,
    isPending: false,
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

const access = vi.hoisted(() => ({ settings: false, org: "org-1" as string | null }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => access.settings }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (state: { activeOrgId: string | null }) => unknown) =>
    select({ activeOrgId: access.org }),
}));

const hooks = vi.hoisted(() => ({
  estimate: undefined as unknown,
  start: undefined as unknown,
}));
vi.mock("@/hooks/use-eval-runs", () => ({
  useEvalRuns: () => ({ estimate: hooks.estimate, start: hooks.start }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  useDatasets: () => ({
    datasets: [
      { id: "ds-1", name: "refunds", case_count: 20, latest_version: 3 },
      { id: "ds-2", name: "empty", case_count: 0, latest_version: 0 },
    ],
  }),
}));
vi.mock("@/hooks/use-agent-environments", () => ({
  useAgentEnvironments: () => ({ environments: [{ id: "env-1", name: "staging" }] }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({
    profiles: [
      { id: "m1", label: "GPT" },
      { id: "m2", label: "Claude" },
    ],
  }),
}));

function open(props: Partial<Parameters<typeof StartEvalDialog>[0]> = {}) {
  const onOpenChange = vi.fn();
  render(
    <StartEvalDialog
      agentId="agent-1"
      canRunDraft
      currentVersion={7}
      onOpenChange={onOpenChange}
      {...props}
    />,
  );
  return onOpenChange;
}

async function choose(combobox: string, option: string) {
  await userEvent.click(screen.getByRole("combobox", { name: combobox }));
  await userEvent.click(screen.getByRole("option", { name: option }));
}

beforeEach(() => {
  vi.clearAllMocks();
  access.settings = false;
  access.org = "org-1";
  hooks.estimate = mutation();
  hooks.start = mutation();
});

describe("StartEvalDialog", () => {
  it("estimates exactly what was chosen, and nothing before a dataset is", async () => {
    open();
    const button = screen.getByRole("button", { name: "Estimate cost" });
    expect(button).toBeDisabled();

    await choose("Dataset", "refunds · 20 cases · v3");
    expect(screen.queryByRole("option", { name: /empty/ })).not.toBeInTheDocument();
    await choose("What runs", "The draft as it stands");
    await choose("Environment", "staging");
    await userEvent.click(screen.getByLabelText("GPT"));
    await userEvent.click(screen.getByLabelText("Claude"));
    await userEvent.click(screen.getByLabelText("GPT"));
    await userEvent.click(screen.getByLabelText("Run the previous version in the same run"));
    await userEvent.click(screen.getByLabelText("Answer tools from recordings"));
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));

    const estimate = hooks.estimate as Mutation;
    expect(estimate.mutate).toHaveBeenCalledWith({
      dataset_id: "ds-1",
      candidate: "draft",
      environment_id: "env-1",
      model_profile_ids: ["m2"],
      paired_baseline: true,
      from_recordings: true,
      live_reads: false,
    });
    // Every change asks for a new estimate, so nothing stale is consented to.
    expect(estimate.reset).toHaveBeenCalled();
  });

  it("runs what was estimated and opens the run", async () => {
    hooks.estimate = mutation({ data: ESTIMATE });
    hooks.start = mutation({ mutateAsync: vi.fn().mockResolvedValue(evalRun()) });
    const onOpenChange = open();

    await choose("Environment", "None");
    await userEvent.click(screen.getByRole("button", { name: "Run for $0.30" }));

    expect((hooks.start as Mutation).mutateAsync).toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(push).toHaveBeenCalledWith("/agents/agent-1/evals/run-1");
  });

  it("refuses to run what the budget cannot hold, and says why the server refused", async () => {
    hooks.estimate = mutation({ data: { ...ESTIMATE, affordable: false } });
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
    hooks.estimate = mutation({ data: ESTIMATE });
    hooks.start = mutation({ mutateAsync: vi.fn().mockRejectedValue(new Error("402")) });
    const onOpenChange = open();

    await userEvent.click(screen.getByRole("button", { name: "Run for $0.30" }));

    expect(onOpenChange).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
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
    access.settings = true;
    open();
    expect(screen.getByRole("link", { name: "Open the organization's settings" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members",
    );
  });

  it("shows no settings link to who cannot change them, or for another refusal", () => {
    const off = new ApiError(400, "off", {
      error: { code: "BAD_REQUEST", message: "off", details: { reason: "ai_assistance_off" } },
    });
    hooks.estimate = mutation({ error: off });
    open();
    expect(screen.queryByRole("link", { name: /organization's settings/ })).toBeNull();
  });

  it("offers only what the caller may run", async () => {
    open({ canRunDraft: false, currentVersion: 7 });
    await userEvent.click(screen.getByRole("combobox", { name: "What runs" }));
    expect(screen.getByRole("option", { name: "Published version v7" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "The draft as it stands" })).toBeNull();
  });

  it("starts on the draft for an agent nobody published", async () => {
    open({ currentVersion: null });
    await choose("Dataset", "refunds · 20 cases · v3");
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    expect((hooks.estimate as Mutation).mutate).toHaveBeenCalledWith(
      expect.objectContaining({ candidate: "draft" }),
    );
  });

  it("runs the published version when it is chosen", async () => {
    open({ currentVersion: 7 });
    await choose("What runs", "Published version v7");
    await choose("Dataset", "refunds · 20 cases · v3");
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    expect((hooks.estimate as Mutation).mutate).toHaveBeenCalledWith(
      expect.objectContaining({ candidate: "version" }),
    );
  });
});
