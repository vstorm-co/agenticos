import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import { UnsavedChangesGuard } from "@/components/layout/unsaved-changes-guard";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { GenerateCasesDialog } from "./generate-cases-dialog";
import { GeneratePanel } from "./generate-panel";

const { estimate, start, granted } = vi.hoisted(() => ({
  estimate: { mutateAsync: vi.fn(), isPending: false },
  start: { mutateAsync: vi.fn(), isPending: false },
  granted: { perms: [] as string[], agentsError: null as Error | null, refetch: vi.fn() },
}));
vi.mock("@/hooks/use-case-generation", () => ({
  useGenerateCases: () => ({ estimate, start }),
  useCaseGenerations: () => ({ generations: [] }),
  useCaseProposals: () => ({
    proposals: [],
    total: 0,
    hidden: 0,
    isLoading: false,
    error: null,
    isDeciding: false,
    refetch: vi.fn(),
    accept: { mutate: vi.fn(), mutateAsync: vi.fn() },
    dismiss: { mutate: vi.fn() },
  }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [{ id: "a1", slug: "support-clerk", name: "Support clerk" }],
    error: granted.agentsError,
    refetch: granted.refetch,
  }),
  useAgentsOfKind: () => ({
    agents: [
      {
        id: "generator",
        name: "Selected generator",
        system_key: null,
        status: "published",
        current_version_id: "v1",
        published_model: null,
      },
    ],
    isLoading: false,
    error: null,
  }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => granted.perms.includes(perm) }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

const ESTIMATE = {
  count: 20,
  sources: [
    { source: "agent", cases: 10, material: 4 },
    { source: "red_team", cases: 10, material: 0 },
  ],
  excluded_collections: 0,
  estimated_cost_usd: "0.12",
};

function mount() {
  const onOpenChange = vi.fn();
  const onStarted = vi.fn();
  render(
    <GenerateCasesDialog datasetId="d1" open onOpenChange={onOpenChange} onStarted={onStarted} />,
  );
  return { onOpenChange, onStarted };
}

async function chooseAgent() {
  await userEvent.click(screen.getByRole("combobox", { name: /Agent/ }));
  await userEvent.click(screen.getByRole("option", { name: "Support clerk" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  granted.perms = [Perm.runsView];
  granted.agentsError = null;
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
});

describe("GenerateCasesDialog", () => {
  it("shows an agent-list error and lets the reader retry", async () => {
    granted.agentsError = new Error("Agents unavailable");
    mount();
    expect(screen.getByRole("alert")).toHaveTextContent("Agents unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(granted.refetch).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Estimate cost" })).toBeDisabled();
  });

  it("starts from the empty queue and returns there after the confirmed generation", async () => {
    estimate.mutateAsync.mockResolvedValue(ESTIMATE);
    start.mutateAsync.mockResolvedValue({ id: "g1" });
    render(<GeneratePanel datasetId="d1" />);
    expect(screen.getByText("No generated cases yet")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Generate cases" }));
    await chooseAgent();
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    await screen.findByText("20 cases, estimated $0.12");
    expect(start.mutateAsync).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(start.mutateAsync).toHaveBeenCalledWith({
      agent_id: "a1",
      sources: ["agent", "red_team"],
      count: 20,
    });
    expect(screen.getByRole("button", { name: "Generate cases" })).toBeVisible();
  });

  it("estimates first, then starts exactly what was estimated", async () => {
    estimate.mutateAsync.mockResolvedValue(ESTIMATE);
    start.mutateAsync.mockResolvedValue({ id: "g1" });
    const { onOpenChange, onStarted } = mount();
    expect(screen.getByRole("button", { name: "Estimate cost" })).toBeDisabled();
    expect(screen.getByText(/Nothing is run against it\./)).toBeInTheDocument();

    await chooseAgent();
    await userEvent.click(screen.getByLabelText(/From knowledge/));
    await userEvent.click(screen.getByLabelText(/From the agent/));
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));

    expect(estimate.mutateAsync).toHaveBeenCalledWith({
      agent_id: "a1",
      sources: ["knowledge", "red_team"],
      count: 20,
    });
    expect(await screen.findByText("20 cases, estimated $0.12")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Generate" }));
    expect(start.mutateAsync).toHaveBeenCalledWith({
      agent_id: "a1",
      sources: ["knowledge", "red_team"],
      count: 20,
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(onStarted).toHaveBeenCalledOnce();
    expect(toast.success).toHaveBeenCalled();
  });

  it("requires a whole number of cases before estimating", async () => {
    mount();
    await chooseAgent();
    const count = screen.getByLabelText("Number of cases");
    await userEvent.clear(count);
    await userEvent.type(count, "2.5");
    expect(screen.getByRole("button", { name: "Estimate cost" })).toBeDisabled();
    expect(estimate.mutateAsync).not.toHaveBeenCalled();
  });

  it("ignores a quote that arrives after the generation request changes", async () => {
    let resolveQuote: (value: typeof ESTIMATE) => void = () => {
      throw new Error("Estimate has not started");
    };
    estimate.mutateAsync.mockReturnValueOnce(
      new Promise<typeof ESTIMATE>((resolve) => {
        resolveQuote = resolve;
      }),
    );
    mount();
    await chooseAgent();
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    const count = screen.getByLabelText("Number of cases");
    await userEvent.clear(count);
    await userEvent.type(count, "50");
    await act(async () => resolveQuote(ESTIMATE));

    expect(screen.queryByRole("button", { name: "Generate" })).toBeNull();
    expect(screen.getByRole("button", { name: "Estimate cost" })).toBeEnabled();
    expect(start.mutateAsync).not.toHaveBeenCalled();

    estimate.mutateAsync.mockResolvedValueOnce({ ...ESTIMATE, count: 50 });
    start.mutateAsync.mockResolvedValueOnce({ id: "g1" });
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    await userEvent.click(await screen.findByRole("button", { name: "Generate" }));
    expect(start.mutateAsync).toHaveBeenCalledWith({
      agent_id: "a1",
      sources: ["agent", "red_team"],
      count: 50,
    });
  });

  it("opens on the agent and count it was given, and estimates those", async () => {
    estimate.mutateAsync.mockResolvedValue(ESTIMATE);
    render(
      <GenerateCasesDialog
        datasetId="d1"
        open
        onOpenChange={vi.fn()}
        initial={{ agentId: "a1", count: 5 }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    expect(estimate.mutateAsync).toHaveBeenCalledWith({
      agent_id: "a1",
      sources: ["agent", "red_team"],
      count: 5,
    });
  });

  it("throws the estimate away when anything changes", async () => {
    estimate.mutateAsync.mockResolvedValue(ESTIMATE);
    mount();
    await chooseAgent();
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    await screen.findByText("20 cases, estimated $0.12");

    const count = screen.getByLabelText("Number of cases");
    await userEvent.clear(count);
    await userEvent.type(count, "8");

    expect(screen.queryByText(/estimated \$/)).toBeNull();
    expect(screen.getByRole("button", { name: "Estimate cost" })).toBeEnabled();
    await userEvent.clear(count);
    await userEvent.type(count, "80");
    expect(screen.getByRole("button", { name: "Estimate cost" })).toBeDisabled();
  });

  it("offers conversations only to a member who may view runs", () => {
    granted.perms = [];
    mount();
    expect(screen.getByLabelText(/From chats/)).toBeDisabled();
    expect(screen.getByText("Needs permission to view runs")).toBeInTheDocument();
  });

  it("shows a refused source under the sources, and anything else as a toast", async () => {
    estimate.mutateAsync.mockRejectedValueOnce(
      new ApiError(400, "refused", {
        error: {
          code: "BAD_REQUEST",
          message: "refused",
          details: {
            fields: [{ field: "sources", message: "Nobody has asked this agent anything yet" }],
          },
        },
      }),
    );
    mount();
    await chooseAgent();
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    expect(await screen.findByText("Nobody has asked this agent anything yet")).toBeInTheDocument();

    estimate.mutateAsync.mockResolvedValueOnce(ESTIMATE);
    await userEvent.click(screen.getByLabelText(/From the agent/));
    await userEvent.click(screen.getByLabelText(/From the agent/));
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    start.mutateAsync.mockRejectedValueOnce(new Error("offline"));
    await userEvent.click(await screen.findByRole("button", { name: "Generate" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("opens the folded count when the count is what was refused", async () => {
    estimate.mutateAsync.mockRejectedValueOnce(
      new ApiError(400, "refused", {
        error: {
          code: "BAD_REQUEST",
          message: "refused",
          details: { fields: [{ field: "count", message: "Ask for at most 12 cases here" }] },
        },
      }),
    );
    mount();
    await chooseAgent();
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));

    expect(await screen.findByText("Ask for at most 12 cases here")).toBeInTheDocument();
    expect(screen.getByLabelText("Number of cases")).toBeInTheDocument();
  });

  it("closes on cancel", async () => {
    const { onOpenChange } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("asks before dropping the choices made, with no Save that would start it", async () => {
    const onOpenChange = vi.fn();
    render(
      <>
        <GenerateCasesDialog datasetId="d1" open onOpenChange={onOpenChange} />
        <UnsavedChangesGuard />
      </>,
    );
    await chooseAgent();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

it("uses dataset settings instead of choosing an agent for generation", () => {
  mount();
  expect(screen.getByText(/Uses the model and instructions saved/)).toBeInTheDocument();
  expect(screen.queryByRole("combobox", { name: "Run with" })).toBeNull();
});
