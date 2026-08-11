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
    created_by_user_id: null,
    is_active: true,
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
    webhook_path: null,
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
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount({ canManage = true } = {}) {
  render(<TriggersPanel agentId={AGENT_ID} canManage={canManage} />, { wrapper });
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

  it("shows none of the row actions to someone who may not manage them", async () => {
    serve([trigger()]);
    await mount({ canManage: false });

    await waitFor(() => expect(screen.getByText("Every 15 minutes")).toBeVisible());
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
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

  it("removes a trigger through its row action", async () => {
    const user = userEvent.setup();
    serve([trigger()]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await user.click(await screen.findByRole("button", { name: "Delete" }));

    expect(apiClient.delete).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1`);
  });

  it("creates an interval schedule from the new-schedule dialog", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Do the thing");
    const count = within(dialog).getByLabelText("Run every");
    await user.clear(count);
    await user.type(count, "2");
    await user.click(within(dialog).getByRole("combobox", { name: "Unit" }));
    await user.click(await screen.findByRole("option", { name: "hours" }));
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Do the thing",
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "interval",
      // Two hours, in seconds.
      interval_seconds: 7200,
    });
  });

  it("creates a GitHub event trigger with its signing secret", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(
      trigger({ trigger_type: "event", event_source: "github", interval_seconds: null }),
    );
    await mount();

    await user.click(await screen.findByRole("button", { name: "New trigger" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Triage it");
    await user.type(within(dialog).getByLabelText("Signing secret"), "a-strong-shared-secret");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Triage it",
      trigger_type: "event",
      environment_id: null,
      event_source: "github",
      event_secret: "a-strong-shared-secret",
      event_config: undefined,
    });
  });

  it("fills the signing secret with a generated one", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New trigger" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));

    expect(
      within(dialog).getByLabelText<HTMLInputElement>("Signing secret").value.length,
    ).toBeGreaterThanOrEqual(16);
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

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers/t1`, {
      prompt: "Reworded",
      environment_id: null,
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
    await user.click(within(dialog).getByRole("tab", { name: "At a set time" }));
    const cron = within(dialog).getByLabelText("Cron expression");
    await user.clear(cron);
    await user.type(cron, "0 9 * * *");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Daily digest",
      trigger_type: "schedule",
      environment_id: null,
      schedule_kind: "cron",
      cron_expression: "0 9 * * *",
    });
  });

  it("creates an email event trigger with a subject filter", async () => {
    const user = userEvent.setup();
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(
      trigger({ trigger_type: "event", event_source: "email", interval_seconds: null }),
    );
    await mount();

    await user.click(await screen.findByRole("button", { name: "New trigger" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Message"), "Reply to it");
    await user.click(within(dialog).getByRole("combobox", { name: "Fires on" }));
    await user.click(await screen.findByRole("option", { name: "An inbound email" }));
    await user.type(within(dialog).getByLabelText("Signing secret"), "another-strong-secret");
    await user.type(within(dialog).getByLabelText("Subject contains"), "urgent");
    await user.type(within(dialog).getByLabelText("Sender contains"), "boss");
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Reply to it",
      trigger_type: "event",
      environment_id: null,
      event_source: "email",
      event_secret: "another-strong-secret",
      event_config: { subject_contains: "urgent", sender_contains: "boss" },
    });
  });

  it("shows an event trigger's webhook url when editing it", async () => {
    const user = userEvent.setup();
    serve([
      trigger({
        trigger_type: "event",
        event_source: "github",
        interval_seconds: null,
        webhook_path: "/api/v1/webhooks/triggers/github/t1",
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
    await user.click(within(dialog).getByRole("button", { name: "Create" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(within(dialog).getByLabelText<HTMLInputElement>("Message").value).toBe("Do it");
  });

  it("will not create a trigger without a message", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Create" })).toBeDisabled();
  });

  it("switches the new dialog from a schedule to an event", async () => {
    const user = userEvent.setup();
    serve([]);
    await mount();

    await user.click(await screen.findByRole("button", { name: "New schedule" }));
    const dialog = await screen.findByRole("dialog");
    // Opens as a schedule - its cadence tabs are present.
    expect(within(dialog).getByRole("tab", { name: "Every so often" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("tab", { name: "Trigger" }));
    // Now the event fields are shown instead.
    expect(within(dialog).getByLabelText("Signing secret")).toBeInTheDocument();
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
