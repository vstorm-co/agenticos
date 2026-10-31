import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { LogAlertRule } from "@/lib/workflows/types";

import { LogAlerts } from "./log-alerts";

const hook = vi.hoisted(() => ({
  rules: [] as unknown[],
  loading: false,
  error: null as Error | null,
  refetch: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
  failed: vi.fn(),
}));
vi.mock("@/hooks", () => ({
  useWorkflowLogAlerts: () => ({
    rules: hook.rules,
    isLoading: hook.loading,
    error: hook.error,
    refetch: hook.refetch,
    create: { mutateAsync: hook.create, isPending: false },
    update: { mutateAsync: hook.update, mutate: hook.update, isPending: false },
    remove: { mutateAsync: hook.remove, isPending: false },
    failed: hook.failed,
  }),
  useMembers: () => ({
    members: [
      { user_id: "u1", email: "ada@acme.test", full_name: "Ada Lovelace" },
      { user_id: "u2", email: "bob@acme.test", full_name: "Bob Ross" },
    ],
  }),
}));
vi.mock("@/stores", () => ({ useOrgStore: () => "org" }));
const toasts = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: toasts.error } }));

const CHOICES = {
  steps: [
    ["n1", "Fetch lead"],
    ["n2", "Decide"],
  ] as [string, string][],
  stepPorts: new Map([
    ["n1", ["error", "out"]],
    ["n2", ["error", "true"]],
  ]),
  labels: new Map([["out", "Done"]]),
  livePorts: null as Map<string, string[]> | null,
};

function rule(overrides: Partial<LogAlertRule> = {}): LogAlertRule {
  return {
    id: "r1",
    workflow_id: "wf",
    name: "Too many failures",
    outcomes: ["error", "out"],
    node_instance_id: "n1",
    message_contains: "timeout",
    threshold: 5,
    window_minutes: 15,
    audience: ["admins", "chosen"],
    user_ids: ["u1", "u2"],
    enabled: true,
    last_firing: {
      id: "f1",
      fired_at: "2026-10-28T09:00:00Z",
      count: 7,
      window_start: "2026-10-28T08:45:00Z",
    },
    created_at: "2026-10-27T09:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function view(canEdit = true, livePorts: Map<string, string[]> | null = null) {
  return render(<LogAlerts workflowId="wf" canEdit={canEdit} {...CHOICES} livePorts={livePorts} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  hook.rules = [];
  hook.loading = false;
  hook.error = null;
  hook.create.mockResolvedValue(undefined);
  hook.update.mockResolvedValue(undefined);
  hook.remove.mockResolvedValue(undefined);
});

describe("LogAlerts", () => {
  it("flags an outcome the live version's step no longer logs, and only against the live version", () => {
    hook.rules = [rule({ node_instance_id: "n1", outcomes: ["big"] })];
    view(true, new Map([["n1", ["error", "large"]]]));
    expect(screen.getByText("Not an outcome of the live version: big")).toBeTruthy();
  });

  it("flags nothing without a live version, for a step the live version lacks, or for an outcome it still has", () => {
    hook.rules = [rule({ node_instance_id: "n1", outcomes: ["big"] })];
    const { unmount } = view(true, null);
    expect(screen.queryByText(/Not an outcome/)).toBeNull();
    unmount();
    const gone = view(true, new Map([["n2", ["error"]]]));
    expect(screen.queryByText(/Not an outcome/)).toBeNull();
    gone.unmount();
    view(true, new Map([["n1", ["error", "big"]]]));
    expect(screen.queryByText(/Not an outcome/)).toBeNull();
  });

  it("judges a rule for any step against every step the live version logs", () => {
    hook.rules = [rule({ node_instance_id: null, outcomes: ["big", "large"] })];
    view(true, new Map([["n1", ["error", "large"]]]));
    expect(screen.getByText("Not an outcome of the live version: big")).toBeTruthy();
  });

  it("describes each rule in words: the condition, who it tells, and its last firing", () => {
    hook.rules = [
      rule(),
      rule({
        id: "r2",
        name: "Quiet",
        last_firing: null,
        node_instance_id: null,
        message_contains: null,
        audience: ["owner"],
        user_ids: [],
        enabled: false,
        outcomes: ["true"],
        threshold: 1,
        window_minutes: 1440,
      }),
    ];
    view();

    expect(screen.getByText("2 alerts")).toBeTruthy();
    expect(
      screen.getByText(
        "At least 5 occurrences with outcome error, Done in Fetch lead containing “timeout” within 15 minutes",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Notifies: Admins, 2 people")).toBeTruthy();
    expect(screen.getByText(/Last fired .*, on 7 occurrences/)).toBeTruthy();
    expect(
      screen.getByText("At least 1 occurrence with outcome true within 24 hours"),
    ).toBeTruthy();
    expect(screen.getByText("Has not fired yet")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Alert Too many failures is on" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Alert Quiet is on" })).not.toBeChecked();
  });

  it("names a step no graph has by its id", () => {
    hook.rules = [rule({ node_instance_id: "gone" })];
    view();
    expect(screen.getByText(/in gone containing/)).toBeTruthy();
  });

  it("shows a viewer the rules and none of the controls", () => {
    hook.rules = [rule()];
    view(false);

    expect(screen.getByText("Too many failures")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add alert" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Edit alert/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Delete alert/ })).toBeNull();
    expect(screen.getByRole("switch", { name: /is on/ })).toBeDisabled();
  });

  it("says there are no alerts, differently to someone who can add one", () => {
    const { unmount } = view();
    expect(screen.getByText("No alerts")).toBeTruthy();
    expect(screen.getByText(/Add an alert to tell people/)).toBeTruthy();
    unmount();
    view(false);
    expect(screen.getByText("Nobody has set up an alert on this workflow's log.")).toBeTruthy();
  });

  it("shows a failed read as an error with a retry, not as no alerts", async () => {
    hook.error = new Error("boom");
    view();
    expect(screen.getByText("Could not load the alerts")).toBeTruthy();
    expect(screen.queryByText("No alerts")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(hook.refetch).toHaveBeenCalled();
  });

  it("counts nothing while loading", () => {
    hook.loading = true;
    view();
    expect(screen.queryByText(/^(\d+ alerts?|No alerts)$/)).toBeNull();
  });

  it("switches a rule on or off with only that field", async () => {
    hook.rules = [rule()];
    view();
    await userEvent.click(screen.getByRole("switch", { name: "Alert Too many failures is on" }));
    expect(hook.update).toHaveBeenCalledWith(
      { ruleId: "r1", patch: { enabled: false } },
      { onError: hook.failed },
    );
  });

  it("says why a switch did not take", async () => {
    hook.rules = [rule()];
    hook.update.mockImplementation((_args: unknown, options?: { onError: (e: Error) => void }) =>
      options?.onError(new Error("refused")),
    );
    view();
    await userEvent.click(screen.getByRole("switch", { name: "Alert Too many failures is on" }));
    expect(hook.failed).toHaveBeenCalledWith(new Error("refused"));
  });

  it("deletes a rule only after a confirmation", async () => {
    hook.rules = [rule()];
    view();
    await userEvent.click(screen.getByRole("button", { name: "Delete alert Too many failures" }));
    expect(hook.remove).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete alert" }));
    await waitFor(() => expect(hook.remove).toHaveBeenCalledWith("r1"));
  });

  it("can be cancelled out of a deletion", async () => {
    hook.rules = [rule()];
    view();
    await userEvent.click(screen.getByRole("button", { name: "Delete alert Too many failures" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(hook.remove).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("closes the confirmation when the delete fails", async () => {
    hook.rules = [rule()];
    hook.remove.mockRejectedValue(new Error("no"));
    view();
    await userEvent.click(screen.getByRole("button", { name: "Delete alert Too many failures" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete alert" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

function refusal(field: string, message: string) {
  return new ApiError(422, "Invalid request", {
    error: {
      code: "VALIDATION_ERROR",
      message: "Invalid request",
      details: { fields: [{ field, message }] },
    },
  });
}

describe("the alert dialog", () => {
  async function fill(dialog: HTMLElement) {
    await userEvent.type(within(dialog).getByLabelText("Name"), "x");
    await userEvent.click(within(dialog).getByLabelText("Done"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    return dialog;
  }

  async function open(existing?: LogAlertRule) {
    if (existing !== undefined) hook.rules = [existing];
    view();
    await userEvent.click(
      screen.getByRole("button", {
        name: existing === undefined ? "Add alert" : `Edit alert ${existing.name}`,
      }),
    );
    return screen.findByRole("dialog");
  }

  it("refuses an alert with no name, outcome, audience or a whole threshold, saying why", async () => {
    const dialog = await open();
    const threshold = within(dialog).getByLabelText("Occurrences");
    await userEvent.clear(threshold);
    await userEvent.type(threshold, "0");
    await userEvent.click(within(dialog).getByLabelText("Workflow owner"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(within(dialog).getByText("Give the alert a name")).toBeTruthy();
    expect(within(dialog).getByText("Choose at least one outcome")).toBeTruthy();
    expect(within(dialog).getByText("A whole number from 1 to 1000")).toBeTruthy();
    expect(within(dialog).getByText("Choose who is told")).toBeTruthy();
    expect(hook.create).not.toHaveBeenCalled();
  });

  it("refuses specific people with nobody named", async () => {
    const dialog = await open();
    await userEvent.click(within(dialog).getByLabelText("Specific people"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Specific people is chosen and nobody is named")).toBeTruthy();
  });

  it("creates a rule from what was filled in, naming the step's own outcomes only", async () => {
    const dialog = await open();
    await userEvent.type(within(dialog).getByLabelText("Name"), "  Failures ");
    // With no step, every step's outcomes are offered.
    expect(within(dialog).getByLabelText("true")).toBeTruthy();
    await userEvent.click(within(dialog).getByLabelText("true"));
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Step" }));
    await userEvent.click(await screen.findByRole("option", { name: "Fetch lead" }));
    // The step does not write `true`: it is no longer offered, nor kept.
    expect(within(dialog).queryByLabelText("true")).toBeNull();
    await userEvent.click(within(dialog).getByLabelText("Done"));
    await userEvent.type(within(dialog).getByLabelText("Message contains"), " bad ");
    const threshold = within(dialog).getByLabelText("Occurrences");
    await userEvent.clear(threshold);
    await userEvent.type(threshold, "3");
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Within" }));
    await userEvent.click(await screen.findByRole("option", { name: "1 hour" }));
    await userEvent.click(within(dialog).getByLabelText("Admins"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(hook.create).toHaveBeenCalledWith({
        name: "Failures",
        outcomes: ["out"],
        node_instance_id: "n1",
        message_contains: "bad",
        threshold: 3,
        window_minutes: 60,
        audience: ["owner", "admins"],
        user_ids: [],
        enabled: true,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("goes back to every step's outcomes when the step is cleared", async () => {
    const dialog = await open(rule());
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Step" }));
    await userEvent.click(await screen.findByRole("option", { name: "Any step" }));
    expect(within(dialog).getByLabelText("true")).toBeTruthy();
    expect(within(dialog).getByLabelText("Done")).toBeChecked();
  });

  it("opens a new rule telling the owner only, with a hint under every field", async () => {
    const dialog = await open();
    expect(within(dialog).getByLabelText("Workflow owner")).toBeChecked();
    expect(within(dialog).getByLabelText("Admins")).not.toBeChecked();
    for (const hint of [
      "What you will see in the list and in the notification",
      "Watch one step, or every step that logs",
      "Which results count. Only ones the step's log writes are listed.",
      "Optional. Only count log messages with these words, in any case.",
      "How many times it has to happen",
      "Within how long",
      "Who gets the bell and the email",
    ]) {
      expect(within(dialog).getByText(hint)).toBeTruthy();
    }
  });

  it("opens a rule as it stands and saves the change with its chosen people", async () => {
    const dialog = await open(rule());
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Too many failures");
    expect(within(dialog).getByLabelText("Occurrences")).toHaveValue(5);
    expect(within(dialog).getByRole("button", { name: "2 people" })).toBeTruthy();

    // Remove one person, then switch the rule off.
    await userEvent.click(within(dialog).getByRole("button", { name: "2 people" }));
    await userEvent.click(await screen.findByRole("option", { name: /Bob Ross/ }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(within(dialog).getByLabelText("Alert is on"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(hook.update).toHaveBeenCalledWith({
        ruleId: "r1",
        patch: expect.objectContaining({
          user_ids: ["u1"],
          enabled: false,
          audience: ["admins", "chosen"],
          node_instance_id: "n1",
          message_contains: "timeout",
        }),
      }),
    );
  });

  it("drops the chosen people when that audience is unticked", async () => {
    const dialog = await open(rule());
    await userEvent.click(within(dialog).getByLabelText("Specific people"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(hook.update).toHaveBeenCalledWith({
        ruleId: "r1",
        patch: expect.objectContaining({ audience: ["admins"], user_ids: [] }),
      }),
    );
  });

  it("keeps a stored step and outcomes the graph no longer has visible", async () => {
    const dialog = await open(rule({ node_instance_id: "gone", outcomes: ["lost"] }));
    expect(within(dialog).getByRole("combobox", { name: "Step" })).toHaveTextContent("gone");
    expect(within(dialog).getByLabelText("lost")).toBeChecked();
  });

  it("keeps the dialog open and names the field the server refused", async () => {
    hook.create.mockRejectedValue(
      new ApiError(422, "Invalid request", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid request",
          details: { fields: [{ field: "threshold", message: "Too high for this window" }] },
        },
      }),
    );
    const dialog = await open();
    await userEvent.type(within(dialog).getByLabelText("Name"), "x");
    await userEvent.click(within(dialog).getByLabelText("Done"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(hook.create).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(within(screen.getByRole("dialog")).getByText("Too high for this window")).toBeTruthy();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it("toasts a refusal that names no field of the form", async () => {
    hook.create.mockRejectedValue(new Error("down"));
    const dialog = await open();
    await userEvent.type(within(dialog).getByLabelText("Name"), "x");
    await userEvent.click(within(dialog).getByLabelText("Done"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(toasts.error).toHaveBeenCalledWith("down"));
  });

  it("puts a refusal of the step under the step", async () => {
    hook.create.mockRejectedValue(refusal("node_instance_id", "That step does not log"));
    await fill(await open());
    expect(await screen.findByText("That step does not log")).toBeTruthy();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it("puts a refusal of the window and of the people under their own fields", async () => {
    hook.create.mockRejectedValueOnce(refusal("window_minutes", "Not a window"));
    const dialog = await open();
    await fill(dialog);
    expect(await screen.findByText("Not a window")).toBeTruthy();
    hook.create.mockRejectedValueOnce(refusal("user_ids", "Not a member"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Not a member")).toBeTruthy();
    expect(toasts.error).not.toHaveBeenCalled();
  });

  it("offers with no step only what some step's quick log writes", async () => {
    render(
      <LogAlerts
        workflowId="wf"
        canEdit
        steps={[["n1", "Fetch lead"]]}
        stepPorts={new Map([["n1", ["error", "out"]]])}
        labels={new Map([["no", "Declined"]])}
        livePorts={null}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Add alert" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("error")).toBeTruthy();
    expect(within(dialog).getByLabelText("out")).toBeTruthy();
    expect(within(dialog).queryByLabelText("Declined")).toBeNull();
  });

  it("closes without saving on Cancel", async () => {
    const dialog = await open();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(hook.create).not.toHaveBeenCalled();
  });
});
