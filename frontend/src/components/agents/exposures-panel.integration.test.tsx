import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExposuresPanel } from "./exposures-panel";
import { apiClient } from "@/lib/api-client";
import type { Exposure, ExposureTarget } from "@/types/exposures";

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

function exposure(overrides: Partial<Exposure> = {}): Exposure {
  return {
    id: "e1",
    agent_id: AGENT_ID,
    surface: "slack",
    channel_bot_id: "b1",
    channel_bot_name: "Acme Support",
    is_active: true,
    max_per_run_usd: null,
    monthly_usd: null,
    created_at: null,
    ...overrides,
  };
}

function target(overrides: Partial<ExposureTarget> = {}): ExposureTarget {
  return { id: "b1", platform: "slack", name: "Acme Support", is_active: true, ...overrides };
}

function serve(exposures: Exposure[], targets: ExposureTarget[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/agents/${AGENT_ID}/exposures`) {
      return { items: exposures, total: exposures.length };
    }
    if (path === `/agents/${AGENT_ID}/exposures/targets`) {
      return { items: targets, total: targets.length };
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount({ canManage = true } = {}) {
  render(<ExposuresPanel agentId={AGENT_ID} canManage={canManage} />, { wrapper });
  await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ExposuresPanel", () => {
  it("says an agent is available nowhere rather than showing an empty box", async () => {
    serve([], [target()]);
    await mount();

    expect(await screen.findByText("Not available on any channel yet.")).toBeInTheDocument();
  });

  it("names each place a person would recognise", async () => {
    serve([exposure()], []);
    await mount();

    expect(await screen.findByText("Slack - Acme Support")).toBeInTheDocument();
  });

  it("says out loud that a paused binding answers nothing", async () => {
    // Silence here reads as the agent ignoring people, which is the state this
    // section exists to explain.
    serve([exposure({ is_active: false })], []);
    await mount();

    expect(
      await screen.findByText("Paused - the handle answers nothing here."),
    ).toBeInTheDocument();
  });

  it("does not offer a bot the agent already answers on", async () => {
    // Binding twice is refused by the server; offering it would spend a round
    // trip to tell somebody what the picker already knew.
    serve([exposure({ channel_bot_id: "b1" })], [target({ id: "b1" }), target({ id: "b2" })]);
    await mount();

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a channel" }));

    expect(screen.queryAllByRole("option")).toHaveLength(1);
  });

  it("binds the bot that was picked", async () => {
    serve([], [target({ id: "b2", platform: "telegram", name: "Ops bot" })]);
    vi.mocked(apiClient.post).mockResolvedValue(exposure({ channel_bot_name: "Ops bot" }));
    await mount();

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a channel" }));
    await userEvent.click(await screen.findByRole("option", { name: /Ops bot/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(apiClient.post).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures`, {
      channel_bot_id: "b2",
    });
  });

  it("hides every control from somebody who cannot publish the agent", async () => {
    // Where an agent is available is `agents:publish` on the server. A viewer
    // seeing live buttons would only learn that from a 403.
    serve([exposure()], [target({ id: "b2" })]);
    await mount({ canManage: false });

    await screen.findByText("Slack - Acme Support");
    expect(screen.queryByRole("combobox", { name: "Add a channel" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause on Acme Support" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove from Acme Support" })).toBeDisabled();
  });

  it("pauses a binding without removing it", async () => {
    serve([exposure()], []);
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ is_active: false }));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Pause on Acme Support" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      is_active: false,
    });
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("removes a binding when asked to", async () => {
    serve([exposure()], []);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove from Acme Support" }));

    expect(apiClient.delete).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`);
  });
});

describe("ExposuresPanel spending limits", () => {
  it("says out loud when a binding can spend without a ceiling", async () => {
    // A blank cell reads as "nothing to see", and an uncapped binding is the one
    // thing on this screen worth noticing.
    serve([exposure()], []);
    await mount();

    expect(await screen.findByText("No spending limit")).toBeInTheDocument();
  });

  it("shows both caps when both are set", async () => {
    serve([exposure({ max_per_run_usd: "0.50", monthly_usd: "25" })], []);
    await mount();

    expect(await screen.findByText("$0.50 per conversation · $25 per month")).toBeInTheDocument();
  });

  it("sends only the limits when they are saved", async () => {
    // Not `is_active` too: the server writes exactly what it is sent, so
    // including it here would let saving a cap resume a binding somebody paused.
    serve([exposure()], []);
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ monthly_usd: "25" }));
    await mount();

    await userEvent.click(
      await screen.findByRole("button", { name: "Set spending limits for Acme Support" }),
    );
    await userEvent.type(screen.getByLabelText("Max per month (USD)"), "25");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      max_per_run_usd: null,
      monthly_usd: "25",
    });
  });

  it("clears a cap when the field is emptied", async () => {
    serve([exposure({ monthly_usd: "25" })], []);
    vi.mocked(apiClient.patch).mockResolvedValue(exposure());
    await mount();

    await userEvent.click(
      await screen.findByRole("button", { name: "Set spending limits for Acme Support" }),
    );
    await userEvent.clear(screen.getByLabelText("Max per month (USD)"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      max_per_run_usd: null,
      monthly_usd: null,
    });
  });

  it("does not offer the limits to somebody who cannot publish the agent", async () => {
    serve([exposure()], []);
    await mount({ canManage: false });

    expect(
      await screen.findByRole("button", { name: "Set spending limits for Acme Support" }),
    ).toBeDisabled();
  });
});
