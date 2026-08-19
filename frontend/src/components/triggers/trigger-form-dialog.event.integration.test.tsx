import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerFormDialog } from "./trigger-form-dialog";
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
    name: null,
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
    environment_id: null,
    trigger_type: "event",
    schedule_kind: "interval",
    interval_seconds: null,
    cron_expression: null,
    event_source: "github",
    event_config: {},
    prompt: "Triage it",
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

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async () => ({ items: [], total: 0 }));
}

/** The event form, as reached from the portal grid's "Advanced: custom webhook". */
async function openEvent() {
  render(<TriggerFormDialog agentId={AGENT_ID} open initialType="event" onOpenChange={vi.fn()} />, {
    wrapper,
  });
  return within(await screen.findByRole("dialog"));
}

/** Open-state controlled, so a "Done" that closes the dialog actually unmounts it. */
function ControlledEventDialog() {
  const [open, setOpen] = useState(true);
  return (
    <TriggerFormDialog agentId={AGENT_ID} open={open} initialType="event" onOpenChange={setOpen} />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

/**
 * The raw source-and-secret event form - the "Advanced: custom webhook" hatch for
 * a provider no portal covers. It is no longer a default create path (the portal
 * grid is), so it is exercised here directly rather than through a panel button.
 */
describe("TriggerFormDialog custom-webhook event form", () => {
  it("offers no schedule/event type switch - the kind is fixed by the entry point", async () => {
    const dialog = await openEvent();

    expect(dialog.queryByRole("tab", { name: "Every so often" })).toBeNull();
    expect(dialog.getByLabelText("Signing secret")).toBeInTheDocument();
  });

  it("creates a GitHub event trigger with its signing secret", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    const dialog = await openEvent();

    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Triage it");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Triage it",
      name: null,
      trigger_type: "event",
      environment_id: null,
      event_source: "github",
      event_secret: "a-strong-shared-secret",
      event_config: undefined,
    });
  });

  it("reveals the webhook url to paste after creating an event trigger", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    vi.mocked(apiClient.post).mockResolvedValue(
      trigger({ webhook_url: "https://api.example.com/api/v1/webhooks/triggers/github/t1" }),
    );
    render(<ControlledEventDialog />, { wrapper });
    let dialog = within(await screen.findByRole("dialog"));

    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Triage");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    // The dialog does not just close: an event trigger needs its URL pasted into
    // the provider, so it stays open on that URL with a way to copy it.
    dialog = within(await screen.findByRole("dialog"));
    const url = dialog.getByLabelText<HTMLInputElement>("Webhook URL");
    expect(url.value).toBe("https://api.example.com/api/v1/webhooks/triggers/github/t1");
    await user.click(dialog.getByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith(url.value);

    await user.click(dialog.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("creates a LinkedIn event trigger with its author and text filters", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(trigger({ event_source: "linkedin" }));
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));
    await user.click(await screen.findByRole("option", { name: "A LinkedIn post" }));
    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    await user.type(dialog.getByLabelText("Author contains"), "Jane");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Draft a reply");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Draft a reply",
      name: null,
      trigger_type: "event",
      environment_id: null,
      event_source: "linkedin",
      event_secret: "a-strong-shared-secret",
      event_config: { author_contains: "Jane" },
    });
  });

  it("creates a generic webhook trigger, which takes no filters", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(trigger({ event_source: "webhook" }));
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));
    await user.click(await screen.findByRole("option", { name: "Any webhook" }));
    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    // No filter inputs for the generic webhook - filtering is the sender's job.
    expect(dialog.queryByLabelText("Subject contains")).toBeNull();
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Handle it");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Handle it",
      name: null,
      trigger_type: "event",
      environment_id: null,
      event_source: "webhook",
      event_secret: "a-strong-shared-secret",
      event_config: undefined,
    });
  });

  it("creates an email event trigger with a subject filter", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(trigger({ event_source: "email" }));
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));
    await user.click(await screen.findByRole("option", { name: "An inbound email" }));
    await user.type(dialog.getByLabelText("Signing secret"), "another-strong-secret");
    await user.type(dialog.getByLabelText("Subject contains"), "urgent");
    await user.type(dialog.getByLabelText("Sender contains"), "boss");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Reply to it");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Reply to it",
      name: null,
      trigger_type: "event",
      environment_id: null,
      event_source: "email",
      event_secret: "another-strong-secret",
      event_config: { subject_contains: "urgent", sender_contains: "boss" },
    });
  });

  it("fills the signing secret with a generated one", async () => {
    const user = userEvent.setup();
    const dialog = await openEvent();

    await user.click(dialog.getByRole("button", { name: "Generate" }));

    expect(
      dialog.getByLabelText<HTMLInputElement>("Signing secret").value.length,
    ).toBeGreaterThanOrEqual(16);
  });

  it("marks each event source in the Fires on picker", async () => {
    const user = userEvent.setup();
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));
    // Every source carries a mark beside its name, not four bare words.
    const option = await screen.findByRole("option", { name: "A LinkedIn post" });
    expect(option.querySelector("svg")).not.toBeNull();
  });
});
