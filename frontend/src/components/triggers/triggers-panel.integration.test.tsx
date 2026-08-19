import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggersPanel } from "./triggers-panel";
import { apiClient } from "@/lib/api-client";
import type { Trigger } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The event path is the portal grid, whose internals are covered by the portal
// tests; here it is stubbed so the panel's own job - opening it - is what is tested.
vi.mock("@/components/triggers/new-event-trigger-dialog", () => ({
  NewEventTriggerDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="New event trigger" /> : null,
}));

const AGENT_ID = "a1";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: AGENT_ID,
    agent_name: null,
    name: null,
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
    environment_id: null,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 900,
    cron_expression: null,
    event_source: null,
    event_config: {},
    prompt: "Summarise the day",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: null,
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function serve(triggers: Trigger[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/agents/${AGENT_ID}/triggers`) {
      return { items: triggers, total: triggers.length };
    }
    if (path === `/agents/${AGENT_ID}/environments`) {
      return { items: [], total: 0 };
    }
    // The New-schedule flow reads the seeded template catalog; empty here so the
    // picker stays out of the way of these create tests.
    if (path === "/schedule-templates") {
      return { items: [], total: 0 };
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount({ canCreate = true } = {}) {
  render(<TriggersPanel agentId={AGENT_ID} canCreate={canCreate} />, { wrapper });
  await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
}

beforeEach(() => vi.clearAllMocks());

describe("TriggersPanel", () => {
  it("says the agent runs only when messaged rather than showing an empty box", async () => {
    serve([]);
    await mount();

    expect(await screen.findByText("This agent runs only when someone messages it.")).toBeVisible();
  });

  it("summarises a schedule by its cadence and shows its message", async () => {
    serve([trigger({ interval_seconds: 900 })]);
    await mount();

    await waitFor(() => expect(screen.getByText("Every 15 minutes")).toBeVisible());
    expect(screen.getByText("Summarise the day")).toBeVisible();
  });

  it("names an event trigger by its source", async () => {
    serve([trigger({ trigger_type: "event", event_source: "github", interval_seconds: null })]);
    await mount();

    await waitFor(() => expect(screen.getByText("On new GitHub issues")).toBeVisible());
  });

  it("opens the portal grid as the default path to a new event trigger", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New event trigger" }));

    // The portal grid is the default event path; the raw form is demoted to its
    // "Advanced: custom webhook" hatch, so the panel opens the grid, not the form.
    expect(await screen.findByRole("dialog", { name: "New event trigger" })).toBeInTheDocument();
  });

  it("hides the create buttons from someone who may not create a trigger", async () => {
    // The panel's `canCreate` is an agent-level signal that gates only the
    // create buttons; an existing row decides its own controls from `can_manage`.
    serve([trigger()]);
    await mount({ canCreate: false });

    await waitFor(() => expect(screen.getByText("Every 15 minutes")).toBeVisible());
    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
  });

  it("hides a row's actions when the caller may not manage that row", async () => {
    // The caller may create here (`canCreate` true), but the server has decided
    // this particular row is read-only for them, so its controls do not render.
    serve([trigger({ can_manage: false })]);
    await mount({ canCreate: true });

    await waitFor(() => expect(screen.getByText("Every 15 minutes")).toBeVisible());
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("pauses a trigger through its row action", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: false }));
    await mount();

    await user.click(await screen.findByRole("button", { name: "Pause" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1`, {
      is_active: false,
    });
  });

  it("marks a paused trigger and refuses to run it now", async () => {
    serve([trigger({ is_active: false })]);
    await mount();

    await waitFor(() => expect(screen.getByText("Paused")).toBeVisible());
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
  });

  it("fires a trigger on demand through its row action", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "Run now" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1/run`, {});
  });

  it("removes a trigger, but only after the delete is confirmed", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await user.click(await screen.findByRole("button", { name: "Delete" }));
    // A destructive one-click delete is a trap; the row asks first.
    expect(apiClient.delete).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1`),
    );
  });

  it("creates an interval schedule from the new-schedule dialog", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Do the thing");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    const count = within(dialog).getByLabelText("Run every");
    await user.clear(count);
    await user.type(count, "2");
    await user.click(within(dialog).getByRole("combobox", { name: "Unit" }));
    await user.click(await screen.findByRole("option", { name: "hours" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Do the thing",
      name: null,
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "interval",
      // Two hours, in seconds.
      interval_seconds: 7200,
    });
  });

  it("edits only the message and the environment of an existing trigger", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ prompt: "Reworded" }));
    await mount();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    const message = within(dialog).getByLabelText("Message");
    await user.clear(message);
    await user.type(message, "Reworded");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    // Only the field that changed: the environment was not touched, so it is not
    // echoed back (which would overwrite a concurrent rebind).
    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1`, {
      prompt: "Reworded",
    });
  });

  it("edits the message through the shared markdown source/preview editor", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    // The message field is the same MarkdownEditor the agent's instructions use,
    // so it carries that field's source/preview toggle rather than a bare box.
    expect(within(dialog).getByRole("button", { name: "Source" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Preview" })).toBeInTheDocument();
  });

  it("leads an event trigger row with its source mark", async () => {
    serve([trigger({ trigger_type: "event", event_source: "github", interval_seconds: null })]);
    await mount({ canCreate: false });

    const summary = await screen.findByText("On new GitHub issues");
    const row = summary.closest("div.rounded-md");
    expect(row?.querySelector("svg")).not.toBeNull();
  });

  it("fires an every-N-days preset as a continuous interval, not a day-of-month step", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Every couple of days");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.click(within(dialog).getByRole("tab", { name: "At a set time" }));
    await user.click(within(dialog).getByRole("combobox", { name: "Repeat" }));
    await user.click(await screen.findByRole("option", { name: "Every few days" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    // `*/2` on day-of-month resets at each month boundary; an interval repeats
    // continuously, which is what "every 2 days" promises. Two days, in seconds.
    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Every couple of days",
      name: null,
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "interval",
      interval_seconds: 172800,
    });
  });

  it("does not resend a non-round cadence when only the message is edited", async () => {
    const user = userEvent.setup();
    // 90s is not a whole number of minutes, so seeding the editor rounds it for
    // display; a prompt-only edit must still not send that rounded value back and
    // reset the schedule's clock.
    serve([trigger({ interval_seconds: 90 })]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ interval_seconds: 90 }));
    await mount();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    const message = within(dialog).getByLabelText("Message");
    await user.clear(message);
    await user.type(message, "Reworded");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1`, {
      prompt: "Reworded",
    });
  });

  it("creates a cron schedule from the set-time tab", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Daily digest");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.click(within(dialog).getByRole("tab", { name: "At a set time" }));
    // The builder opens on "every day at 09:00", which composes to 0 9 * * * with
    // nobody having to write crontab - the whole point of the redesign.
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Daily digest",
      name: null,
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "cron",
      cron_expression: "0 9 * * *",
    });
  });

  it("creates a weekday-morning schedule from one preset pill", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Morning digest");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    const pill = within(dialog).getByRole("button", { name: "Weekdays 09:00" });
    await user.click(pill);
    // The pill lights, and the builder underneath now spells out what it set.
    expect(pill).toHaveAttribute("aria-pressed", "true");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Morning digest",
      name: null,
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "cron",
      cron_expression: "0 9 * * 1,2,3,4,5",
    });
  });

  it("creates a six-hourly schedule from one preset pill, still editable below", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Sweep the queue");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    const pill = within(dialog).getByRole("button", { name: "Every 6h" });
    await user.click(pill);
    // A preset is a shortcut into the builder, not a mode: editing the interval
    // underneath unlights the pill and wins.
    const count = within(dialog).getByLabelText("Run every");
    expect(count).toHaveValue(6);
    await user.clear(count);
    await user.type(count, "8");
    expect(pill).toHaveAttribute("aria-pressed", "false");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Sweep the queue",
      name: null,
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "interval",
      // Eight hours, in seconds - the hand edit, not the preset's six.
      interval_seconds: 28800,
    });
  });

  it("shows an event trigger's webhook url when editing it", async () => {
    const user = userEvent.setup();
    serve([
      trigger({
        trigger_type: "event",
        event_source: "github",
        interval_seconds: null,
        webhook_url: "/api/v1/webhooks/triggers/github/t1",
      }),
    ]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    const url = within(dialog).getByLabelText<HTMLInputElement>("Webhook URL");
    expect(url.value).toContain("/api/v1/webhooks/triggers/github/t1");
  });

  it("runs a trigger now from its editor", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Run now" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1/run`, {});
  });

  it("offers a named environment and sends the one chosen", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === `/agents/${AGENT_ID}/triggers`) return { items: [], total: 0 };
      if (path === `/agents/${AGENT_ID}/environments`) {
        return {
          items: [
            {
              id: "env-2",
              agent_id: AGENT_ID,
              name: "staging",
              version_id: "v3-id",
              version: 3,
              is_default: false,
              logfire_token_secret_id: null,
              service_name: null,
              created_at: "2026-07-01T00:00:00Z",
            },
          ],
          total: 1,
        };
      }
      throw new Error(`unexpected GET ${path}`);
    });
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "x");
    await user.click(within(dialog).getByRole("combobox", { name: "Environment" }));
    await user.click(await screen.findByRole("option", { name: /staging/ }));
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      `/agents/${AGENT_ID}/triggers`,
      expect.objectContaining({ environment_id: "env-2" }),
    );
  });

  it("keeps the dialog open and loses nothing when the server refuses a create", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockRejectedValue(new Error("You cannot run this agent"));
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Do it");
    await user.click(within(dialog).getByRole("button", { name: "Continue" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    // Stepping back shows the message untouched - the refusal cost nothing typed.
    await user.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(within(dialog).getByLabelText<HTMLInputElement>("Message").value).toBe("Do it");
  });

  it("will not create a trigger without a message", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    // The task step will not even advance without a message, so nothing
    // downstream can create one.
    expect(within(dialog).getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("closes on cancel without creating anything", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
