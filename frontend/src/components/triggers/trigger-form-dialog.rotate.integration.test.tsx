import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
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

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function eventTrigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: null,
    name: null,
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
    environment_id: null,
    runs_as_creator: false,
    trigger_type: "event",
    schedule_kind: "interval",
    interval_seconds: null,
    cron_expression: null,
    time_zone: null,
    overlap: "skip",
    event_source: "github",
    event_config: {},
    prompt: "Triage it",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: null,
    webhook_url: "https://api.example.com/api/v1/webhooks/triggers/github/t1",
    portal_key: null,
    delivery_mode: "manual",
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
    path === "/me/permissions" ? { permissions: [] } : { items: [], total: 0 },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

describe("TriggerFormDialog rotate secret", () => {
  it("rotates a manual trigger's secret and reveals the new one exactly once", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({
      ...eventTrigger(),
      delivery_mode: "manual",
      reveal_secret: "new-secret-value",
    });
    render(
      <TriggerFormDialog agentId="a1" open trigger={eventTrigger()} onOpenChange={vi.fn()} />,
      {
        wrapper,
      },
    );

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Rotate signing secret" }));

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/triggers/t1/rotate-secret", {});
    // The new secret is shown so the user can paste it into the provider - once.
    const field = await within(dialog).findByLabelText<HTMLInputElement>("Signing secret");
    expect(field.value).toBe("new-secret-value");
    expect(within(dialog).getByText(/won't be shown again/)).toBeVisible();
  });

  it("says an auto-webhook trigger was re-registered rather than revealing a secret", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({
      ...eventTrigger({ delivery_mode: "auto_webhook" }),
      reveal_secret: null,
    });
    render(
      <TriggerFormDialog agentId="a1" open trigger={eventTrigger()} onOpenChange={vi.fn()} />,
      {
        wrapper,
      },
    );

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Rotate signing secret" }));

    expect(await within(dialog).findByText(/re-registered the webhook/)).toBeVisible();
    // Nothing to paste - the platform holds the new secret, so no field is shown.
    expect(within(dialog).queryByLabelText("Signing secret")).toBeNull();
  });

  it("does not offer rotation on a trigger the caller may not manage", async () => {
    render(
      <TriggerFormDialog
        agentId="a1"
        open
        trigger={eventTrigger({ can_manage: false })}
        onOpenChange={vi.fn()}
      />,
      { wrapper },
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Rotate signing secret" })).toBeNull();
  });
});

describe("Polled trigger editing", () => {
  it.each(["google_drive", "microsoft_files", "google_calendar", "outlook_calendar"] as const)(
    "edits %s filters and hides webhook credential actions",
    async (source) => {
      render(
        <TriggerFormDialog
          agentId="a1"
          open
          trigger={eventTrigger({
            event_source: source,
            delivery_mode: "polling",
            webhook_url: null,
            event_config:
              source === "microsoft_files"
                ? { site_url: "https://acme.sharepoint.com/sites/Finance", folder_path: "Invoices" }
                : source === "google_drive"
                  ? { folder_id: "folder", name_contains: "invoice" }
                  : { subject_contains: "Review", attendee_contains: "@client.test" },
          })}
          onOpenChange={vi.fn()}
        />,
        { wrapper },
      );
      const dialog = within(await screen.findByRole("dialog"));
      expect(dialog.queryByRole("button", { name: "Rotate signing secret" })).toBeNull();
      expect(dialog.getAllByRole("textbox").length).toBeGreaterThanOrEqual(4);
    },
  );
});

it("saves calendar options while retaining its other filters", async () => {
  const trigger = eventTrigger({
    event_source: "outlook_calendar",
    delivery_mode: "polling",
    event_config: { subject_contains: "Review", external_only: true, minutes_before: 15 },
  });
  vi.mocked(apiClient.patch).mockResolvedValue(trigger);
  render(<TriggerFormDialog agentId="a1" open trigger={trigger} onOpenChange={vi.fn()} />, {
    wrapper,
  });
  const dialog = within(await screen.findByRole("dialog"));
  fireEvent.change(dialog.getByLabelText("Minutes before the meeting"), {
    target: { value: "60" },
  });
  await userEvent.click(dialog.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", {
      event_config: { subject_contains: "Review", external_only: true, minutes_before: 60 },
    }),
  );
});
