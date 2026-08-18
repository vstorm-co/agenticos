import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
    webhook_url: "https://api.example.com/api/v1/webhooks/triggers/github/t1",
    portal_key: null,
    delivery_mode: "manual",
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async () => ({ items: [], total: 0 }));
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
