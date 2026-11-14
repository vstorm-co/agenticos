import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WatchDialog } from "./watch-dialog";
import type { Watch, WatchPreset } from "@/lib/watches-api";

/**
 * Setting up a watch (#2301): a preset fills in its words in the person's
 * language and keeps to the organization's floor, the person's own words work
 * too, and a change to an existing one carries what to leave out.
 */

const state = vi.hoisted(() => ({
  floor: 15 as number | null,
  presets: [] as WatchPreset[],
  create: vi.fn(),
  update: vi.fn(),
  path: "/mcp-servers",
  push: vi.fn(),
}));
const toastSuccess = vi.hoisted(() => vi.fn());
const toastError = vi.hoisted(() => vi.fn());
const refusal = vi.hoisted(() => ({
  value: null as null | { fields: Record<string, string>; toast: string | null },
}));

vi.mock("@/hooks", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "a-monitor",
        name: "Monitor",
        slug: "monitor",
        can_run: true,
        current_version_id: "v1",
      },
    ],
    isLoading: false,
  }),
  useAgentEnvironments: () => ({ environments: [] }),
  useMcpConnections: () => ({
    connections: [
      { id: "c-gh", name: "github", label: null, catalog_key: "github" },
      { id: "c-mine", name: "intranet", label: "Our wiki", catalog_key: null },
    ],
  }),
  useOrganizations: () => ({
    activeOrg: state.floor === null ? null : { proactive_watch_min_minutes: state.floor },
  }),
  useMcpCatalog: () => ({
    servers: [{ key: "github", name: "GitHub", icon: "github", url: null }],
  }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => state.path,
  useRouter: () => ({ push: state.push }),
}));
vi.mock("@/hooks/use-watches", () => ({
  useWatchPresets: () => state.presets,
  useWatches: () => ({ create: state.create, update: state.update }),
}));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
vi.mock("@/lib/api-error", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-error")>();
  return {
    ...actual,
    submitFailure: (...args: Parameters<typeof actual.submitFailure>) =>
      refusal.value ?? actual.submitFailure(...args),
  };
});

const REVIEWS: WatchPreset = {
  key: "github-reviews",
  server: "github",
  instructions: "Pull requests where my review is requested.",
  interval_minutes: 60,
  urgent: false,
};
const FAILING: WatchPreset = {
  key: "github-failing-checks",
  server: "github",
  instructions: "My own open pull requests whose checks are failing.",
  interval_minutes: 60,
  urgent: true,
};

const watch = (overrides: Partial<Watch> = {}): Watch => ({
  id: "w1",
  agent_id: "a-monitor",
  environment_id: null,
  pinned_version_id: null,
  source_conversation_id: null,
  ends_at: null,
  connection_id: "c-gh",
  connection_name: "github",
  server: "github",
  preset_key: "github-reviews",
  title: "Reviews",
  instructions: "Waiting on me",
  exclusions: ["dependabot"],
  urgent: false,
  interval_minutes: 60,
  is_active: true,
  stopped: null,
  next_run_at: "2026-10-22T10:00:00Z",
  last_run_at: null,
  last_attempt_at: null,
  last_attempt_status: null,
  waiting: 0,
  created_at: "2026-10-22T09:00:00Z",
  ...overrides,
});

beforeEach(() => {
  state.floor = 15;
  state.presets = [REVIEWS, FAILING, { ...REVIEWS, key: "linear-assigned", server: "linear" }];
  state.create.mockReset().mockResolvedValue(undefined);
  state.update.mockReset().mockResolvedValue(undefined);
  state.path = "/mcp-servers";
  state.push.mockReset();
  refusal.value = null;
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("WatchDialog", () => {
  it("persists an explicit disabled failure policy", async () => {
    render(<WatchDialog open onOpenChange={vi.fn()} watch={watch()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Pause after repeated failures" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Do not pause for repeated execution failures" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(state.update).toHaveBeenCalledWith(
      expect.objectContaining({ changes: expect.objectContaining({ max_failures: null }) }),
    );
  });
  it("saves an explicit no-change report and app-only delivery together", async () => {
    render(<WatchDialog open onOpenChange={vi.fn()} watch={watch()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "When to report" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "After every check, including no changes" }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Notifications for this routine" }));
    await userEvent.click(await screen.findByRole("option", { name: "In the app only" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(state.update).toHaveBeenCalledWith(
      expect.objectContaining({
        changes: expect.objectContaining({ report_mode: "every_check", notification_channels: [] }),
      }),
    );
  });
  it("requires an explicit agent in the global creation flow", async () => {
    render(<WatchDialog open onOpenChange={vi.fn()} connectionId="c-gh" />);
    await userEvent.click(screen.getByRole("combobox", { name: "What to look for" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Pull requests waiting on my review" }),
    );
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.click(await screen.findByRole("option", { name: "Monitor" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Create routine" }));
    expect(state.create).toHaveBeenCalledWith(expect.objectContaining({ agent_id: "a-monitor" }));
  });
  it("preserves the exact stored end on an unrelated edit and only refreshes sources explicitly", async () => {
    const endsAt = "2027-01-02T03:04:05.123456Z";
    render(<WatchDialog open onOpenChange={vi.fn()} watch={watch({ ends_at: endsAt })} />);
    await userEvent.click(screen.getByRole("switch", { name: "Approve attached sources again" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const changes = state.update.mock.calls[0]![0].changes;
    expect(changes.review_sources).toBe(true);
    expect(changes).not.toHaveProperty("ends_at");
  });
  it("fills a preset in the person's words, within the organization's floor", async () => {
    state.floor = 180;
    const onOpenChange = vi.fn();
    render(
      <WatchDialog agentId="a-monitor" open onOpenChange={onOpenChange} connectionId="c-gh" />,
    );

    // Only the presets for this connection's server, and one's own words.
    expect(screen.queryByRole("radio", { name: "Issues assigned to me" })).toBeNull();
    await userEvent.click(screen.getByRole("combobox", { name: "What to look for" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Failing checks on my pull requests" }),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Failing checks on my pull requests");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("switch", { name: "Tell me at once when it is urgent" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "How often" })).toHaveTextContent("Every 3 hours");
    await userEvent.click(screen.getByRole("button", { name: "Create routine" }));

    expect(state.create).toHaveBeenCalledWith({
      agent_id: "a-monitor",
      environment_id: null,
      pinned_version_id: null,
      ends_at: null,
      connection_id: "c-gh",
      preset_key: "github-failing-checks",
      title: "Failing checks on my pull requests",
      instructions: "My own open pull requests whose checks are failing.",
      urgent: true,
      interval_minutes: 180,
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    // Started from an account's menu, it says where the watch now lives.
    const [message, options] = toastSuccess.mock.calls[0]!;
    expect(message).toBe("Watching - the first look is within a minute");
    expect(options.description).toBe(
      "It is under Routines, and what it finds lands in your inbox.",
    );
    options.action.onClick();
    expect(state.push).toHaveBeenCalledWith("/routines?tab=watches");
  });

  it("names each account by its server, and offers no way to Routines from Routines", async () => {
    state.path = "/pl/routines";
    render(<WatchDialog agentId="a-monitor" open onOpenChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Account" }));
    expect(await screen.findByRole("option", { name: "GitHub" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "Our wiki" }));
    await userEvent.type(screen.getByLabelText("Name"), "Wiki");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Look for"), "Pricing");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Create routine" }));

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    expect(toastSuccess.mock.calls[0]![1].action).toBeUndefined();
  });

  it("takes the person's own words for a server with no presets", async () => {
    state.floor = null;
    render(<WatchDialog agentId="a-monitor" open onOpenChange={vi.fn()} />);
    const start = screen.getByRole("button", { name: "Continue" });
    expect(start).toBeDisabled();

    await userEvent.click(screen.getByRole("combobox", { name: "Account" }));
    await userEvent.click(await screen.findByRole("option", { name: "Our wiki" }));
    expect(screen.queryByRole("radio", { name: "Something else" })).toBeNull();
    await userEvent.type(screen.getByLabelText("Name"), "  Wiki edits ");
    await userEvent.click(start);
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Look for"), "Pages about pricing");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("combobox", { name: "How often" }));
    await userEvent.click(await screen.findByRole("option", { name: "Every 15 minutes" }));
    await userEvent.click(screen.getByRole("button", { name: "Create routine" }));

    expect(state.create).toHaveBeenCalledWith({
      agent_id: "a-monitor",
      environment_id: null,
      pinned_version_id: null,
      ends_at: null,
      connection_id: "c-mine",
      preset_key: null,
      title: "Wiki edits",
      instructions: "Pages about pricing",
      urgent: false,
      interval_minutes: 15,
    });
  });

  it("goes back to one's own words from a preset", async () => {
    render(<WatchDialog agentId="a-monitor" open onOpenChange={vi.fn()} connectionId="c-gh" />);
    await userEvent.click(screen.getByRole("combobox", { name: "What to look for" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Pull requests waiting on my review" }),
    );
    await userEvent.click(screen.getByRole("combobox", { name: "What to look for" }));
    await userEvent.click(await screen.findByRole("option", { name: "Something else" }));
    expect(screen.getByRole("combobox", { name: "What to look for" })).toHaveTextContent(
      "Something else",
    );
    // What the preset wrote stays, to edit from.
    expect(screen.getByLabelText("Name")).toHaveValue("Pull requests waiting on my review");
  });

  it("changes a watch it was opened with, what to leave out included", async () => {
    const onOpenChange = vi.fn();
    render(<WatchDialog agentId="a-monitor" open onOpenChange={onOpenChange} watch={watch()} />);
    expect(screen.getByRole("combobox", { name: "Account" })).toBeDisabled();
    expect(screen.queryByRole("radio")).toBeNull();
    await userEvent.type(screen.getByLabelText("Leave out"), "\nrenovate");
    await userEvent.click(
      screen.getByRole("switch", { name: "Tell me at once when it is urgent" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(state.update).toHaveBeenCalledWith({
      id: "w1",
      changes: {
        environment_id: null,
        pinned_version_id: null,
        title: "Reviews",
        instructions: "Waiting on me",
        urgent: true,
        interval_minutes: 60,
        exclusions: ["dependabot", "renovate"],
      },
    });
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Watch saved"));
  });

  it("puts a refusal under the field it names and toasts the rest", async () => {
    refusal.value = { fields: { interval_minutes: "Too often" }, toast: "Also this" };
    state.update.mockRejectedValue(new Error("400"));
    render(<WatchDialog agentId="a-monitor" open onOpenChange={vi.fn()} watch={watch()} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Too often")).toBeVisible();
    expect(toastError).toHaveBeenCalledWith("Also this");
  });

  it("says nothing more than the field when that is all the refusal named", async () => {
    refusal.value = { fields: { title: "Taken" }, toast: null };
    state.update.mockRejectedValue(new Error("400"));
    render(<WatchDialog agentId="a-monitor" open onOpenChange={vi.fn()} watch={watch()} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Taken")).toBeVisible();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("keeps the draft when moving back and exposes just one advanced panel", async () => {
    render(<WatchDialog open agentId="a-monitor" connectionId="c-gh" onOpenChange={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Name"), "My review queue");
    expect(screen.queryByRole("textbox", { name: "Look for" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.type(screen.getByLabelText("Look for"), "Find reviews waiting on me");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getAllByText("Advanced options")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Look for")).toHaveValue("Find reviews waiting on me");
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Name")).toHaveValue("My review queue");
    expect(state.create).not.toHaveBeenCalled();
  });

  it("returns a create refusal to the step containing the rejected field", async () => {
    refusal.value = { fields: { title: "Taken" }, toast: null };
    state.create.mockRejectedValue(new Error("400"));
    render(
      <WatchDialog
        open
        agentId="a-monitor"
        connectionId="c-gh"
        onOpenChange={vi.fn()}
        initialTask={{ title: "My reviews", instructions: "Find reviews" }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Create routine" }));
    expect(await screen.findByText("Taken")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("My reviews");
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  });

  it.each(["Cancel", "Close"])("closes on %s", async (action) => {
    const onOpenChange = vi.fn();
    render(<WatchDialog agentId="a-monitor" open onOpenChange={onOpenChange} watch={watch()} />);
    await userEvent.click(screen.getByRole("button", { name: action }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

it("starts a proposed watch with a visible cadence that respects a nonstandard floor", async () => {
  state.floor = 90;
  render(
    <WatchDialog
      open
      agentId="a-monitor"
      connectionId="c-gh"
      onOpenChange={vi.fn()}
      initialTask={{ title: "My reviews", instructions: "Find review requests" }}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("combobox", { name: "How often" })).toHaveTextContent("Every 90 minutes");
  await userEvent.click(screen.getByRole("button", { name: "Create routine" }));
  expect(state.create).toHaveBeenCalledWith(
    expect.objectContaining({
      title: "My reviews",
      instructions: "Find review requests",
      interval_minutes: 90,
      urgent: false,
    }),
  );
});

vi.mock("./watch-agent-fields", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./watch-agent-fields")>();
  return {
    ...actual,
    WatchExecutionFields: ({
      onEnvironment,
      onVersion,
    }: {
      onEnvironment: (id: string | null) => void;
      onVersion: (id: string | null) => void;
    }) => (
      <>
        <button onClick={() => onEnvironment("prod")}>Select production environment</button>
        <button onClick={() => onEnvironment(null)}>Select default environment</button>
        <button onClick={() => onVersion("pinned-version")}>Pin reviewed version</button>
      </>
    ),
  };
});
it("saves explicit version and end-time changes without silently refreshing source consent", async () => {
  render(<WatchDialog open onOpenChange={vi.fn()} watch={watch()} />);
  await userEvent.click(screen.getByRole("button", { name: "Select production environment" }));
  await userEvent.click(screen.getByRole("button", { name: "Select default environment" }));
  await userEvent.click(screen.getByRole("button", { name: "Pin reviewed version" }));
  fireEvent.change(screen.getByLabelText("Ends at (device time)"), {
    target: { value: "2028-01-02T03:04" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.update).toHaveBeenCalledWith(
    expect.objectContaining({
      changes: expect.objectContaining({
        environment_id: null,
        pinned_version_id: "pinned-version",
        ends_at: expect.stringContaining("2028-"),
      }),
    }),
  );
});

it("rechecks an edited end time at submission even if time advanced after validation", async () => {
  render(<WatchDialog open onOpenChange={vi.fn()} watch={watch()} />);
  fireEvent.change(screen.getByLabelText("Ends at (device time)"), {
    target: { value: "2028-01-02T03:04" },
  });
  const clock = vi.spyOn(Date, "now").mockReturnValue(new Date("2029-01-01T00:00:00Z").getTime());
  try {
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(state.update).not.toHaveBeenCalled();
  } finally {
    clock.mockRestore();
  }
});
it.each(["instructions", "interval_minutes"])(
  "returns a rejected create to the %s step without losing the draft",
  async (field) => {
    refusal.value = { fields: { [field]: "Please revise this" }, toast: null };
    state.create.mockRejectedValue(new Error("Rejected"));
    render(
      <WatchDialog
        open
        agentId="a-monitor"
        connectionId="c-gh"
        onOpenChange={vi.fn()}
        initialTask={{ title: "My reviews", instructions: "Find reviews" }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Create routine" }));
    expect(await screen.findByText("Please revise this")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: field === "instructions" ? "Continue" : "Create routine",
      }),
    ).toBeInTheDocument();
  },
);

it("keeps an edited watch open while saving and retains a refused draft", async () => {
  let reject!: (reason: Error) => void;
  state.update.mockImplementationOnce(
    () =>
      new Promise((_resolve, refuse) => {
        reject = refuse;
      }),
  );
  const onOpenChange = vi.fn();
  render(<WatchDialog open watch={watch()} onOpenChange={onOpenChange} />);
  await userEvent.clear(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Customer reviews");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(state.update).toHaveBeenCalled());
  expect(screen.getByLabelText("Name")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  await userEvent.keyboard("{Escape}");
  expect(onOpenChange).not.toHaveBeenCalled();
  reject(new Error("Controlled watch refusal"));
  await waitFor(() => expect(screen.getByLabelText("Name")).toBeEnabled());
  expect(screen.getByLabelText("Name")).toHaveValue("Customer reviews");
  expect(onOpenChange).not.toHaveBeenCalled();
});
