import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgSystemAgents } from "./org-system-agents";
import type { SystemAgent } from "@/lib/system-agents-api";
import type { Organization } from "@/types";
import { Perm, type Permission } from "@/types/permissions";

const state = vi.hoisted(() => ({
  tenantId: "o1" as string | null,
  held: [] as string[],
  roles: undefined as unknown,
  mutateAsync: vi.fn(),
  isPending: false,
  fail: undefined as unknown,
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (permission: Permission) => state.held.includes(permission) }),
  useModelProviders: () => ({ profiles: [], profilesStatus: "loaded" }),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => state.tenantId }));
vi.mock("@/hooks/use-system-agents", () => ({
  useSystemAgents: () => ({
    roles: state.roles,
    update: { mutateAsync: state.mutateAsync, isPending: state.isPending },
  }),
}));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    value,
    onChange,
    onCreationPendingChange,
  }: {
    value: string | null;
    onChange: (id: string | null) => void;
    onCreationPendingChange: (pending: boolean) => void;
  }) => (
    <div>
      <span>picked:{value ?? "none"}</span>
      <button onClick={() => onChange("model-2")}>pick</button>
      <button onClick={() => onCreationPendingChange(true)}>creating</button>
      <button onClick={() => onCreationPendingChange(false)}>created</button>
    </div>
  ),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, values?: Record<string, string>): string =>
      values ? `${key}:${Object.values(values).join("|")}` : key,
  useFormatter: () => ({
    dateTime: () => "1 Nov 2026",
    number: (value: number) => `$${value}`,
  }),
}));

function agent(overrides: Partial<SystemAgent> = {}): SystemAgent {
  return {
    role: "memory_maintenance",
    enabled: false,
    model_profile_id: null,
    model_label: null,
    monthly_budget_usd: null,
    spent_this_month: "0",
    managed_in: null,
    runs: [],
    ...overrides,
  };
}

const briefing = agent({
  role: "daily_briefing",
  enabled: true,
  model_profile_id: "model-1",
  model_label: "Sonnet",
  managed_in: "proactivity",
});

const ORG = { id: "o1", name: "Acme" } as Organization;

beforeEach(() => {
  vi.clearAllMocks();
  state.tenantId = "o1";
  state.held = [Perm.budgetsManage];
  state.roles = [briefing, agent()];
  state.isPending = false;
  state.mutateAsync.mockResolvedValue(agent());
});

describe("OrgSystemAgents", () => {
  it("is for budget managers, and waits for the roles", () => {
    state.held = [];
    expect(render(<OrgSystemAgents org={ORG} />).container).toBeEmptyDOMElement();
    state.held = [Perm.budgetsManage];
    state.roles = undefined;
    expect(render(<OrgSystemAgents org={ORG} />).container).toBeEmptyDOMElement();
  });

  it("is the active organization's: another one's page shows nothing of it", () => {
    state.tenantId = "other";

    expect(render(<OrgSystemAgents org={ORG} />).container).toBeEmptyDOMElement();
  });

  it("shows the briefing as the proactivity setting, with no form of its own", () => {
    render(<OrgSystemAgents org={ORG} />);

    const card = screen.getByTestId("system-agent-daily_briefing");
    expect(card).toHaveTextContent("managedIn:Sonnet");
    expect(card).toHaveTextContent("on");
    expect(card.querySelector("button")).toBeNull();
  });

  it("says when the briefing has no model yet, and when it is off", () => {
    state.roles = [{ ...briefing, enabled: false, model_label: null }, agent()];
    render(<OrgSystemAgents org={ORG} />);

    const card = screen.getByTestId("system-agent-daily_briefing");
    expect(card).toHaveTextContent("managedInNoModel");
    expect(card).toHaveTextContent("off");
  });

  it("lists what each role has done, its spend and its failures", () => {
    state.roles = [
      briefing,
      agent({
        monthly_budget_usd: "5.000000",
        spent_this_month: "1.5",
        runs: [
          {
            id: "r1",
            started_at: "2026-11-01T10:00:00Z",
            status: "completed",
            model_label: "Sonnet",
            cost_usd: "0.01",
            error: null,
          },
          {
            id: "r2",
            started_at: "2026-11-01T11:00:00Z",
            status: "failed",
            model_label: null,
            cost_usd: "0",
            error: "The model timed out",
          },
        ],
      }),
    ];
    render(<OrgSystemAgents org={ORG} />);

    const card = screen.getByTestId("system-agent-memory_maintenance");
    expect(card).toHaveTextContent("spentOf:$1.5|$5");
    expect(card).toHaveTextContent("Sonnet");
    expect(card).toHaveTextContent("unknownModel");
    expect(card).toHaveTextContent("The model timed out");
    expect(screen.getByTestId("system-agent-daily_briefing")).toHaveTextContent("noRuns");
  });

  it("refuses to turn on without a model and a budget that is not a number", async () => {
    render(<OrgSystemAgents org={ORG} />);
    const card = screen.getByTestId("system-agent-memory_maintenance");

    await userEvent.click(card.querySelector("button[role=switch]") as HTMLElement);
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(card).toHaveTextContent("modelRequired");

    await userEvent.type(screen.getByLabelText("budget"), "-1");
    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(card).toHaveTextContent("invalid");
    expect(state.mutateAsync).not.toHaveBeenCalled();
  });

  it("saves the switch, the model and the budget together", async () => {
    render(<OrgSystemAgents org={ORG} />);
    const card = screen.getByTestId("system-agent-memory_maintenance");

    await userEvent.click(card.querySelector("button[role=switch]") as HTMLElement);
    await userEvent.click(screen.getByRole("button", { name: "pick" }));
    await userEvent.type(screen.getByLabelText("budget"), "5");
    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(state.mutateAsync).toHaveBeenCalledWith({
      role: "memory_maintenance",
      change: { enabled: true, model_profile_id: "model-2", monthly_budget_usd: "5" },
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("saved"));
  });

  it("says when it was turned off, and clears the cap when the budget is emptied", async () => {
    state.roles = [
      briefing,
      agent({ enabled: true, model_profile_id: "model-1", monthly_budget_usd: "5" }),
    ];
    render(<OrgSystemAgents org={ORG} />);
    const card = screen.getByTestId("system-agent-memory_maintenance");

    await userEvent.click(card.querySelector("button[role=switch]") as HTMLElement);
    await userEvent.clear(screen.getByLabelText("budget"));
    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(state.mutateAsync).toHaveBeenCalledWith({
      role: "memory_maintenance",
      change: { enabled: false, model_profile_id: "model-1", monthly_budget_usd: null },
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("savedOff"));
  });

  it("holds the save while a model is being created", async () => {
    render(<OrgSystemAgents org={ORG} />);
    await userEvent.type(screen.getByLabelText("budget"), "1");
    const save = screen.getByRole("button", { name: "save" });

    await userEvent.click(screen.getByRole("button", { name: "creating" }));
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "created" }));
    expect(save).toBeEnabled();
  });

  it("reports a refusal under the field the server named", async () => {
    state.mutateAsync.mockRejectedValue(
      Object.assign(new Error("refused"), {
        status: 400,
        details: { fields: { model_profile_id: "That model is not one of this organization's" } },
      }),
    );
    render(<OrgSystemAgents org={ORG} />);
    await userEvent.type(screen.getByLabelText("budget"), "1");
    await userEvent.click(screen.getByRole("button", { name: "save" }));

    await waitFor(() => expect(toastSuccess).not.toHaveBeenCalled());
    await waitFor(() => expect(state.mutateAsync).toHaveBeenCalled());
  });
});
