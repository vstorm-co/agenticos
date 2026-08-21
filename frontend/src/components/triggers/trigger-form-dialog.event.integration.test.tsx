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

/** The event form, as reached from the portal grid's "Advanced: API trigger". */
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
 * The raw source-and-secret event form - the "Advanced: API trigger" hatch for
 * a provider no portal covers. It is no longer a default create path (the portal
 * grid is), so it is exercised here directly rather than through a panel button.
 */
describe("TriggerFormDialog custom-webhook event form", () => {
  it("offers no schedule/event type switch - the kind is fixed by the entry point", async () => {
    const dialog = await openEvent();

    expect(dialog.queryByRole("tab", { name: "Every so often" })).toBeNull();
    expect(dialog.getByLabelText("Signing secret")).toBeInTheDocument();
  });

  it("creates an API event trigger with its signing secret", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
    const dialog = await openEvent();

    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Triage it");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/triggers`, {
      prompt: "Triage it",
      name: null,
      trigger_type: "event",
      environment_id: null,
      // `webhook` because this form is the API-trigger path: the portal grid is
      // how somebody reaches a GitHub or Gmail trigger, and defaulting to GitHub
      // here opened the card they had just chosen *instead of* GitHub on "Fires
      // on: a GitHub issue".
      event_source: "webhook",
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
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.type(dialog.getByLabelText("Message"), "Triage");
    await user.click(dialog.getByRole("button", { name: "Create" }));

    // The dialog does not just close: an event trigger needs its URL pasted into
    // the provider, so it stays open on that URL with a way to copy it.
    dialog = within(await screen.findByRole("dialog"));
    const url = dialog.getByLabelText<HTMLInputElement>("Webhook URL");
    expect(url.value).toBe("https://api.example.com/api/v1/webhooks/triggers/github/t1");
    // And on the secret beside it: the provider form asks for both at once, and
    // the server never echoes a raw trigger's secret back, so the dialog's own
    // copy is the last chance to read a generated one.
    expect(dialog.getByLabelText<HTMLInputElement>("Signing secret").value).toBe(
      "a-strong-shared-secret",
    );
    await user.click(
      within(url.closest("div") as HTMLElement).getByRole("button", { name: "Copy" }),
    );
    expect(writeText).toHaveBeenCalledWith(url.value);

    await user.click(dialog.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("creates a generic API trigger, which takes no filters", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(trigger({ event_source: "webhook" }));
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));
    await user.click(await screen.findByRole("option", { name: "API (your own code)" }));
    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    // No filter inputs for the generic webhook - filtering is the sender's job.
    expect(dialog.queryByLabelText("Subject contains")).toBeNull();
    await user.click(dialog.getByRole("button", { name: "Continue" }));
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

  it("does not offer Gmail at all, because this form is the signed-POST one", async () => {
    // Gmail is read from a connected mailbox: no inbound door, no per-trigger
    // secret. Offering it here would put a Signing secret field on a source that
    // has none, so it is created from its portal card instead (#1068).
    const user = userEvent.setup();
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));

    expect(await screen.findByRole("option", { name: "A GitHub issue" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /email/i })).toBeNull();
    expect(screen.queryByRole("option", { name: /Gmail/i })).toBeNull();
  });

  it("fills the signing secret with a generated one", async () => {
    const user = userEvent.setup();
    const dialog = await openEvent();

    await user.click(dialog.getByRole("button", { name: "Generate" }));

    expect(
      dialog.getByLabelText<HTMLInputElement>("Signing secret").value.length,
    ).toBeGreaterThanOrEqual(16);
  });

  it("offers the source's message templates and prefills the prompt from one", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/trigger-templates") {
        return {
          items: [
            {
              key: "github_triage",
              label: "Triage the new issue",
              description: "Propose a priority and labels",
              prompt: "Triage this issue.",
              trigger_type: "event",
              event_source: "github",
            },
            {
              key: "email_reply",
              label: "Draft a reply",
              description: "Answer the sender",
              prompt: "Draft a reply.",
              trigger_type: "event",
              event_source: "gmail",
            },
            {
              key: "webhook_handle",
              label: "Act on the payload",
              description: "Do something with what was posted",
              prompt: "Act on this payload.",
              trigger_type: "event",
              event_source: "webhook",
            },
          ],
          total: 3,
        };
      }
      return { items: [], total: 0 };
    });
    const dialog = await openEvent();

    await user.type(dialog.getByLabelText("Signing secret"), "a-strong-shared-secret");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(dialog.getByRole("button", { name: "Continue" }));

    // Only the templates written for the source picked on step one - a prompt
    // about an email makes no sense against a signed POST from your own code, and
    // neither does one about a GitHub issue.
    expect(dialog.queryByRole("button", { name: /Draft a reply/ })).toBeNull();
    expect(dialog.queryByRole("button", { name: /Triage the new issue/ })).toBeNull();
    await user.click(dialog.getByRole("button", { name: /Act on the payload/ }));
    expect(dialog.getByLabelText<HTMLTextAreaElement>("Message").value).toBe(
      "Act on this payload.",
    );
  });

  it("marks each event source in the Fires on picker", async () => {
    const user = userEvent.setup();
    const dialog = await openEvent();

    await user.click(dialog.getByRole("combobox", { name: "Fires on" }));
    // Every source carries a mark beside its name, not three bare words.
    const option = await screen.findByRole("option", { name: "API (your own code)" });
    expect(option.querySelector("svg")).not.toBeNull();
  });
});
