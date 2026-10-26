import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import { UnsavedChangesGuard } from "@/components/layout/unsaved-changes-guard";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { GenerateCasesDialog } from "./generate-cases-dialog";

const { estimate, start, granted } = vi.hoisted(() => ({
  estimate: { mutateAsync: vi.fn(), isPending: false },
  start: { mutateAsync: vi.fn(), isPending: false },
  granted: { perms: [] as string[] },
}));
vi.mock("@/hooks/use-case-generation", () => ({
  useGenerateCases: () => ({ estimate, start }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: [{ id: "a1", name: "Support clerk" }] }),
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
  render(<GenerateCasesDialog datasetId="d1" open onOpenChange={onOpenChange} />);
  return { onOpenChange };
}

async function chooseAgent() {
  await userEvent.click(screen.getByRole("combobox", { name: /Agent/ }));
  await userEvent.click(screen.getByRole("option", { name: "Support clerk" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  granted.perms = [Perm.runsView];
  useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
});

describe("GenerateCasesDialog", () => {
  it("estimates first, then starts exactly what was estimated", async () => {
    estimate.mutateAsync.mockResolvedValue(ESTIMATE);
    start.mutateAsync.mockResolvedValue({ id: "g1" });
    const { onOpenChange } = mount();
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
    expect(toast.success).toHaveBeenCalled();
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

    expect(screen.queryByLabelText("Number of cases")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "More options · 20 cases" }));
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

it("discards the old quote when its generator changes", async () => {
  estimate.mutateAsync.mockResolvedValue(ESTIMATE);
  mount();
  await chooseAgent();
  await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
  await userEvent.click(screen.getByText("Case generator"));
  await userEvent.click(screen.getByRole("combobox", { name: "Run with" }));
  await userEvent.click(screen.getByRole("option", { name: "Selected generator" }));
  expect(screen.queryByRole("button", { name: "Generate" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
  expect(estimate.mutateAsync).toHaveBeenLastCalledWith(
    expect.objectContaining({ generator_agent_id: "generator" }),
  );
});
