import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EnvironmentsPanel } from "./environments-panel";
import { ApiError } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { evalSuite, suiteResult, suiteSummary } from "@/test-utils/eval-suites";
import type { AgentEnvironment, AgentVersion } from "@/types/agents";
import type { PromotionGate, PromotionGuard } from "@/types/promotion-gate";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const AGENT_ID = "a1";
const SUITE = evalSuite({ id: "s1", name: "Refunds" });

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function environment(overrides: Partial<AgentEnvironment> = {}): AgentEnvironment {
  return {
    id: "env-prod",
    agent_id: AGENT_ID,
    name: "production",
    version_id: "v1-id",
    version: 1,
    is_default: true,
    tracks_latest: false,
    behind_by: 1,
    logfire_token_secret_id: null,
    service_name: null,
    connections: [],
    guard_suite_ids: [SUITE.id],
    created_at: "2026-10-21T00:00:00Z",
    ...overrides,
  };
}

function version(n: number): AgentVersion {
  return { id: `v${n}-id`, version: n, note: null, published_by_user_id: null };
}

function guard(overrides: Partial<PromotionGuard> = {}): PromotionGuard {
  return {
    suite_id: SUITE.id,
    suite_name: SUITE.name,
    state: "unchecked",
    paused_reason: null,
    result: null,
    ...overrides,
  };
}

function gate(overrides: Partial<PromotionGate> = {}): PromotionGate {
  return {
    environment_id: "env-prod",
    environment_name: "production",
    version_id: "v2-id",
    version: 2,
    guarded: true,
    passing: false,
    can_override: true,
    guards: [guard()],
    ...overrides,
  };
}

let current: PromotionGate;
let permissions: string[];

function serve(environments: AgentEnvironment[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/agents/${AGENT_ID}/environments`) {
      return { items: environments, total: environments.length };
    }
    if (path === `/agents/${AGENT_ID}/versions`)
      return { items: [version(2), version(1)], total: 2 };
    if (path === `/agents/${AGENT_ID}/environments/env-prod/gate`) return current;
    if (path === `/agents/${AGENT_ID}/eval-suites`) return { items: [SUITE], total: 1 };
    if (path === "/me/permissions") {
      return { permissions: permissions.map((permission) => ({ permission, scope: "all" })) };
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

async function openGate() {
  render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
  await userEvent.click(
    await screen.findByRole("combobox", { name: "Pin a version for production" }),
  );
  await userEvent.click(screen.getByRole("option", { name: "v2" }));
  return screen.findByRole("dialog");
}

beforeEach(() => {
  vi.clearAllMocks();
  current = gate();
  permissions = ["promotions:override"];
  serve([environment()]);
  vi.mocked(apiClient.patch).mockResolvedValue(environment());
});

describe("promoting onto a guarded environment", () => {
  it("asks the gate first, naming each guard and what it needs", async () => {
    const dialog = await openGate();

    expect(within(dialog).getByText("Promote v2 to production")).toBeInTheDocument();
    expect(within(dialog).getByText("Refunds")).toBeInTheDocument();
    expect(within(dialog).getByText("Not checked")).toBeInTheDocument();
    expect(within(dialog).getByText("Has not run on this version yet.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Promote" })).toBeDisabled();
    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(apiClient.get).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-prod/gate`, {
      params: { version_id: "v2-id" },
    });
  });

  it("runs the guards on the version and shows them checking", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      started: [SUITE.id],
      gate: gate({ guards: [guard({ state: "checking" })] }),
    });
    const dialog = await openGate();

    await userEvent.click(within(dialog).getByRole("button", { name: "Run the evals on v2" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      `/agents/${AGENT_ID}/environments/env-prod/gate/run`,
      { version_id: "v2-id" },
    );
    expect(await within(dialog).findByText("Checking")).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("Started 1 eval suite");
  });

  it("says why a run of the guards was refused", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("down"));
    const dialog = await openGate();

    await userEvent.click(within(dialog).getByRole("button", { name: "Run the evals on v2" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("words a guard's result with its reasons, its skip or its pause", async () => {
    current = gate({
      guards: [
        guard({
          suite_id: "a",
          state: "failed",
          result: suiteResult({
            status: "failed",
            summary: suiteSummary({
              reasons: [{ code: "regressions", value: 1, limit: 0, detail: null }],
            }),
          }),
        }),
        guard({
          suite_id: "b",
          suite_name: "Tone",
          state: "skipped",
          result: suiteResult({ status: "skipped", reason: "ai_assistance_off", summary: null }),
        }),
        guard({
          suite_id: "e",
          suite_name: "Stopped one",
          state: "inconclusive",
          result: suiteResult({ status: "inconclusive", reason: "cancelled", summary: null }),
        }),
        guard({ suite_id: "c", suite_name: "Paused one", state: "paused", paused_reason: null }),
        guard({
          suite_id: "d",
          suite_name: "Gone owner",
          state: "paused",
          paused_reason: "owner_inactive",
        }),
      ],
    });
    const dialog = await openGate();

    expect(
      within(dialog).getByText("1 case breaks reproducibly; the suite allows 0."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Only the judge could grade these cases, and AI assistance is off."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Its eval run was stopped.")).toBeInTheDocument();
    expect(within(dialog).getByText("Paused: its owner left")).toBeInTheDocument();
    // Two badges, and the hand-paused one's own line.
    expect(within(dialog).getAllByText("Paused")).toHaveLength(3);
  });

  it("promotes once every guard passed", async () => {
    current = gate({ passing: true, guards: [guard({ state: "passed" })] });
    const dialog = await openGate();

    expect(within(dialog).getByText("Every guard passed on v2.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("group", { name: "Promote anyway" })).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Promote" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-prod`, {
      version_id: "v2-id",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("promotes past the guards only with a reason long enough to say something", async () => {
    const dialog = await openGate();
    const override = within(dialog).getByRole("group", { name: "Promote anyway" });
    const submit = within(override).getByRole("button", { name: "Promote past the evals" });

    await userEvent.type(within(override).getByLabelText("Why"), "hotfix");
    expect(submit).toBeDisabled();
    await userEvent.type(within(override).getByLabelText("Why"), " for refunds");
    await userEvent.click(submit);

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-prod`, {
      version_id: "v2-id",
      override_reason: "hotfix for refunds",
    });
  });

  it("offers no override to somebody who may not give one", async () => {
    current = gate({ can_override: false });
    const dialog = await openGate();

    expect(within(dialog).queryByRole("group", { name: "Promote anyway" })).toBeNull();
  });

  it("keeps the dialog open, without a toast, when the gate moved under it", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(
      new ApiError(409, "blocked", { error: { code: "PROMOTION_BLOCKED", message: "x" } }),
    );
    const dialog = await openGate();

    await userEvent.type(within(dialog).getByLabelText("Why"), "hotfix for refunds");
    await userEvent.click(within(dialog).getByRole("button", { name: "Promote past the evals" }));

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    // Read again, so the dialog shows the gate as it is now.
    await waitFor(() =>
      expect(
        vi
          .mocked(apiClient.get)
          .mock.calls.filter(([path]) => path === `/agents/${AGENT_ID}/environments/env-prod/gate`),
      ).toHaveLength(2),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("toasts any other refusal of the promotion", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("down"));
    current = gate({ passing: true, guards: [guard({ state: "passed" })] });
    const dialog = await openGate();

    await userEvent.click(within(dialog).getByRole("button", { name: "Promote" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("says when the gate could not be read, and reads it again on retry", async () => {
    let failing = true;
    const serveGate = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path: string, options?: unknown) => {
      if (path === `/agents/${AGENT_ID}/environments/env-prod/gate` && failing) {
        throw new Error("down");
      }
      return serveGate(path, options as never);
    });
    const dialog = await openGate();

    expect(
      await within(dialog).findByText("Could not read the evals guarding this environment."),
    ).toBeInTheDocument();
    failing = false;
    await userEvent.click(within(dialog).getByRole("button", { name: "Try again" }));

    expect(await within(dialog).findByText("Not checked")).toBeInTheDocument();
  });

  it("closes on cancel or Escape without promoting", async () => {
    const dialog = await openGate();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.click(screen.getByRole("combobox", { name: "Pin a version for production" }));
    await userEvent.click(screen.getByRole("option", { name: "v2" }));
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("promotes an unguarded environment straight through, as before", async () => {
    serve([environment({ guard_suite_ids: [] })]);
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await userEvent.click(
      await screen.findByRole("combobox", { name: "Pin a version for production" }),
    );
    await userEvent.click(screen.getByRole("option", { name: "v2" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-prod`, {
      version_id: "v2-id",
    });
  });
});

describe("an environment's guards", () => {
  it("says how many suites guard it and saves a new set", async () => {
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    expect(await screen.findByText("Guarded by 1 suite")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Eval suites guarding production" }));
    const save = await screen.findByRole("button", { name: "Save guards" });
    await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(save);

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-prod`, {
      guard_suite_ids: [],
    });
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Guards saved"));

    await userEvent.click(screen.getByRole("button", { name: "Eval suites guarding production" }));
    expect(screen.queryByRole("button", { name: "Save guards" })).toBeNull();
  });

  it("adds a suite to the guards", async () => {
    serve([environment({ guard_suite_ids: [] })]);
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "Eval suites guarding production" }),
    );
    await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Save guards" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/environments/env-prod`, {
      guard_suite_ids: [SUITE.id],
    });
  });

  it("says why saving the guards failed", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("down"));
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "Eval suites guarding production" }),
    );
    await waitFor(() => expect(screen.getByRole("checkbox")).not.toBeDisabled());
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", { name: "Save guards" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("shows the guards read-only to somebody who may not change them", async () => {
    permissions = [];
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "Eval suites guarding production" }),
    );

    expect(
      await screen.findByText("Changing these needs permission to override promotions."),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save guards" })).toBeNull();
  });

  it("offers no suite whose dataset has no cases yet as a guard, saying why", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === `/agents/${AGENT_ID}/environments`)
        return { items: [environment({ guard_suite_ids: [] })], total: 1 };
      if (path === `/agents/${AGENT_ID}/versions`) return { items: [version(1)], total: 1 };
      if (path === `/agents/${AGENT_ID}/eval-suites`)
        return { items: [evalSuite({ ...SUITE, dataset_has_cases: false })], total: 1 };
      return { permissions: [] };
    });
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "Eval suites guarding production" }),
    );

    expect(
      await screen.findByText(
        "This suite's dataset has no cases yet. Add cases before it guards an environment.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeDisabled();
  });

  it("says when the agent has no suite to guard with", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === `/agents/${AGENT_ID}/environments`) return { items: [environment()], total: 1 };
      if (path === `/agents/${AGENT_ID}/versions`) return { items: [version(1)], total: 1 };
      if (path === `/agents/${AGENT_ID}/eval-suites`) return { items: [], total: 0 };
      return { permissions: [] };
    });
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "Eval suites guarding production" }),
    );

    expect(await screen.findByText(/This agent has no eval suites yet/)).toBeInTheDocument();
  });

  it("opens the gate for the newest version an environment that follows is waiting on", async () => {
    serve([environment({ tracks_latest: true })]);
    render(<EnvironmentsPanel agentId={AGENT_ID} canManage />, { wrapper });

    await userEvent.click(
      await screen.findByRole("button", { name: "Waiting for its evals on v2" }),
    );

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
