import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerFormDialog } from "./trigger-form-dialog";
import { apiClient } from "@/lib/api-client";
import type { TriggerTemplate } from "@/types/trigger-templates";

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

const DAILY: TriggerTemplate = {
  key: "daily-standup",
  label: "Daily standup",
  description: "Summarise overnight activity",
  prompt: "Summarise what happened overnight.",
  trigger_type: "schedule",
  suggested_cadence: { schedule_kind: "interval", interval_seconds: 86400 },
};

const WEEKLY: TriggerTemplate = {
  key: "weekly-report",
  label: "Weekly report",
  description: "Write the weekly report",
  prompt: "Write this week's report.",
  trigger_type: "schedule",
  suggested_cadence: { schedule_kind: "cron", cron_expression: "0 9 * * 1" },
};

function serve(templates: TriggerTemplate[] = [DAILY, WEEKLY]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/trigger-templates") return { items: templates, total: templates.length };
    if (path === "/agents") {
      return { items: [{ id: "a1", name: "Analyst", status: "published" }], total: 1 };
    }
    // The picked agent's environments and triggers.
    return { items: [], total: 0 };
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

async function open() {
  render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, { wrapper });
  const dialog = within(await screen.findByRole("dialog"));
  // Past the configure step - the templates live with the message they prefill.
  await userEvent.click(dialog.getByRole("button", { name: "Continue" }));
  return dialog;
}

describe("New-schedule template picker", () => {
  it("prefills the prompt and an interval cadence from a template", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({});
    const dialog = await open();

    await user.click(await dialog.findByRole("button", { name: /Daily standup/ }));
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    // The schedule step's interval builder reads the template's cadence: one day.
    expect(dialog.getByLabelText<HTMLInputElement>("Run every").value).toBe("1");

    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/triggers", {
      prompt: "Summarise what happened overnight.",
      name: "Daily standup",
      trigger_type: "schedule",
      environment_id: null,
      overlap: "skip",
      schedule_kind: "interval",
      interval_seconds: 86400,
    });
  });

  it("prefills a cron cadence from a template that suggests one", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({});
    const dialog = await open();

    // A second pick replaces the name the first one wrote.
    await user.click(await dialog.findByRole("button", { name: /Daily standup/ }));
    await user.click(dialog.getByRole("button", { name: /Weekly report/ }));
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/triggers", {
      prompt: "Write this week's report.",
      name: "Weekly report",
      trigger_type: "schedule",
      environment_id: null,
      overlap: "skip",
      schedule_kind: "cron",
      cron_expression: "0 9 * * 1",
    });
  });

  it("opens already filled in from an idea picked before it", async () => {
    // The Routines page's ideas open the form with one chosen: the first frame
    // shows it, rather than a blank form somebody has to pick it in again.
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({});
    render(
      <TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} initialTemplate={WEEKLY} />,
      { wrapper },
    );
    const dialog = within(await screen.findByRole("dialog"));

    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/a1/triggers",
      expect.objectContaining({
        prompt: "Write this week's report.",
        schedule_kind: "cron",
        cron_expression: "0 9 * * 1",
      }),
    );
  });

  it("keeps a name somebody typed when a template is picked after it", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue({});
    render(<TriggerFormDialog agentId="a1" open onOpenChange={vi.fn()} />, { wrapper });
    const dialog = within(await screen.findByRole("dialog"));

    await user.type(dialog.getByLabelText("Name"), "Board update");
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(await dialog.findByRole("button", { name: /Weekly report/ }));
    await user.click(dialog.getByRole("button", { name: "Continue" }));
    await user.click(dialog.getByRole("button", { name: "Create" }));

    expect(apiClient.post).toHaveBeenCalledWith(
      "/agents/a1/triggers",
      expect.objectContaining({ name: "Board update" }),
    );
  });

  it("clears the prefill when starting from scratch", async () => {
    const user = userEvent.setup();
    const dialog = await open();

    await user.click(await dialog.findByRole("button", { name: /Daily standup/ }));
    // The task step can advance once a template fills the prompt.
    expect(dialog.getByRole("button", { name: "Continue" })).toBeEnabled();

    await user.click(dialog.getByRole("button", { name: /Start from scratch/ }));
    // Back to a blank message, so there is nothing to continue with yet.
    expect(dialog.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(dialog.getByRole("button", { name: /Start from scratch/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // The name the template wrote goes with it.
    await user.click(dialog.getByRole("button", { name: "Back" }));
    expect(dialog.getByLabelText<HTMLInputElement>("Name").value).toBe("");
  });

  it("draws a mark on every card, so the grid is scannable", async () => {
    // Four bordered rectangles of two text lines each is a grid nobody reads
    // (#1069). The glyph is keyed on the template's key on this side, because
    // which mark illustrates a card is not the catalog's business.
    const dialog = await open();

    const card = await dialog.findByRole("button", { name: /Daily standup/ });

    expect(card.querySelector("svg")).not.toBeNull();
  });

  it("stays out of the way when the catalog is empty", async () => {
    serve([]);
    const dialog = await open();

    await dialog.findByLabelText("Message");
    expect(dialog.queryByText("Start from a template")).toBeNull();
  });
});
