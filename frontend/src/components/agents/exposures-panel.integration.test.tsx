import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExposuresPanel } from "./exposures-panel";
import { apiClient } from "@/lib/api-client";
import type { AgentEnvironment } from "@/types/agents";
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
    environment_id: null,
    session_scope: null,
    prompt: null,
    tools: [],
    available_tools: [],
    available_variables: [],
    usage_reporting: { mode: "near_limit", near_limit_percent: 80, every_n: 10 },
    is_active: true,
    created_at: null,
    ...overrides,
  };
}

function target(overrides: Partial<ExposureTarget> = {}): ExposureTarget {
  return { id: "b1", platform: "slack", name: "Acme Support", is_active: true, ...overrides };
}

function environment(overrides: Partial<AgentEnvironment> = {}): AgentEnvironment {
  return {
    id: "env-prod",
    agent_id: AGENT_ID,
    name: "production",
    version_id: "v2-id",
    version: 2,
    is_default: true,
    tracks_latest: false,
    behind_by: 0,
    logfire_token_secret_id: null,
    service_name: null,
    created_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function serve(
  exposures: Exposure[],
  targets: ExposureTarget[],
  environments: AgentEnvironment[] = [],
) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === `/agents/${AGENT_ID}/exposures`) {
      return { items: exposures, total: exposures.length };
    }
    if (path === `/agents/${AGENT_ID}/exposures/targets`) {
      return { items: targets, total: targets.length };
    }
    if (path === `/agents/${AGENT_ID}/environments`) {
      return { items: environments, total: environments.length };
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount({ canManage = true, hasWorkspace = true } = {}) {
  render(<ExposuresPanel agentId={AGENT_ID} canManage={canManage} hasWorkspace={hasWorkspace} />, {
    wrapper,
  });
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

  it("names the fix instead of a picker nothing can be picked from", async () => {
    // A disabled select saying "no unbound bots" was a dead end. It said which
    // of two absences this was, which stopped being knowable here: a bot serves
    // one agent, so "every bot registered and every one serving somebody else"
    // looks from the client exactly like "no bots at all". What all of them
    // share is the fix, so that is what it says.
    serve([], []);
    await mount();

    expect(screen.queryByRole("combobox", { name: "Add a channel" })).not.toBeInTheDocument();
    expect(await screen.findByText(/No bot is free to bind/)).toBeInTheDocument();
  });

  it("says the same thing when this agent is on the only bot there is", async () => {
    serve([exposure({ channel_bot_id: "b1" })], [target({ id: "b1" })]);
    await mount();

    expect(await screen.findByText(/No bot is free to bind/)).toBeInTheDocument();
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

  it("resumes a paused binding", async () => {
    serve([exposure({ is_active: false })], []);
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ is_active: true }));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Resume on Acme Support" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      is_active: true,
    });
  });

  it("offers no environment picker when the default is the only environment", async () => {
    // A picker with one option is a control that cannot be used.
    serve([exposure()], [], [environment()]);
    await mount();

    await screen.findByText("Slack - Acme Support");
    expect(screen.queryByRole("combobox", { name: /Environment on/ })).not.toBeInTheDocument();
  });

  it("says which environment a bot is served from, and lets it be moved", async () => {
    // The reason this control exists: a Slack workspace pointed at staging while
    // production serves everyone else is invisible anywhere else in the product.
    serve(
      [exposure()],
      [],
      [environment(), environment({ id: "env-staging", name: "staging", is_default: false })],
    );
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ environment_id: "env-staging" }));
    await mount();

    const picker = await screen.findByRole("combobox", { name: "Environment on Acme Support" });
    expect(picker).toHaveTextContent("default");
    await userEvent.click(picker);
    await userEvent.click(await screen.findByRole("option", { name: "staging (v2)" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      environment_id: "env-staging",
    });
  });

  it("returns a binding to the default environment as an explicit null", async () => {
    // The sentinel exists because a Select item may not be empty; the server
    // reads "back to default" off the null and would ignore an absent field.
    serve(
      [exposure({ environment_id: "env-staging" })],
      [],
      [environment(), environment({ id: "env-staging", name: "staging", is_default: false })],
    );
    vi.mocked(apiClient.patch).mockResolvedValue(exposure());
    await mount();

    await userEvent.click(
      await screen.findByRole("combobox", { name: "Environment on Acme Support" }),
    );
    await userEvent.click(await screen.findByRole("option", { name: "default" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      environment_id: null,
    });
  });

  it("marks a bot that is registered but switched off", async () => {
    // Binding to it is legal and answers nothing; the picker is the only place
    // that says so before somebody wonders why the handle is silent.
    serve([], [target({ id: "b2", name: "Ops bot", is_active: false })]);
    await mount();

    await userEvent.click(await screen.findByRole("combobox", { name: "Add a channel" }));

    // Matched inside the option, not through its accessible name: the mark is
    // `trailing`, and Radix names an item by its `ItemText` alone.
    const off = await screen.findByRole("option", { name: "Slack - Ops bot" });
    expect(within(off).getByText("inactive")).toBeVisible();
  });

  it("does not repeat that mark on the closed trigger, which chose the bot", async () => {
    // Radix draws the selected item's `ItemText` in the trigger, so "(inactive)"
    // in `children` followed the choice out of the list - where it read as the
    // state of the binding somebody had just made rather than of the bot.
    serve([], [target({ id: "b2", name: "Ops bot", is_active: false })]);
    await mount();

    const picker = await screen.findByRole("combobox", { name: "Add a channel" });
    await userEvent.click(picker);
    await userEvent.click(await screen.findByRole("option", { name: "Slack - Ops bot" }));

    // `not.toHaveTextContent`, not `queryByText`: the mark used to be the text
    // node " (inactive)" beside the name, which `queryByText("inactive")` would
    // not have matched - a regression test that passes against the bug.
    expect(picker).toHaveTextContent("Ops bot");
    expect(picker).not.toHaveTextContent("inactive");
  });

  it("warns that an approval parks a channel thread, where files are in play", async () => {
    // Otherwise the bot looks broken while somebody is meant to be switching
    // tabs to approve a shell command.
    serve([exposure()], []);
    await mount();

    expect(await screen.findByText(/the thread sits there meanwhile/)).toBeVisible();
  });

  it("says nothing about approvals for an agent that keeps no files", async () => {
    serve([exposure()], []);
    await mount({ hasWorkspace: false });

    await screen.findByText(/Acme Support/);
    expect(screen.queryByText(/the thread sits there meanwhile/)).toBeNull();
  });

  it("saves extra instructions for one binding only", async () => {
    // The same published agent answers in a dashboard, on a widget and in a
    // Mattermost channel. Editing the spec to suit one changes all of them.
    serve([exposure()], []);
    vi.mocked(apiClient.patch).mockResolvedValue(exposure({ prompt: "Be terse." }));
    await mount();

    await userEvent.type(
      await screen.findByLabelText("Extra instructions on Acme Support"),
      "Be terse.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      prompt: "Be terse.",
    });
  });

  it("offers no workspace-sharing control at all", async () => {
    // Six options, on every binding of every agent, for a question most people
    // never ask: who shares the sandbox. The spec already answers it the way
    // Slack does - a thread is a chat - and somebody who genuinely needs
    // otherwise changes the agent rather than each of its bindings.
    serve([exposure()], []);
    await mount();

    await screen.findByText(/Acme Support/);
    expect(screen.queryByRole("combobox", { name: /Workspace sharing/ })).toBeNull();
  });

  it("offers the channel lookups this platform can actually answer", async () => {
    // Under the binding rather than in the Toolbox, because the answer belongs
    // to the binding: the same agent on an internal Mattermost and a customer
    // Slack gets a different one.
    serve(
      [
        exposure({
          available_tools: [
            { id: "get_channel_info", name: "get_channel_info", description: "Describe it." },
            { id: "read_channel_history", name: "read_channel_history", description: "Read it." },
          ],
          tools: ["get_channel_info"],
        }),
      ],
      [],
    );
    await mount();

    expect(await screen.findByText("What this agent may look up on Slack")).toBeInTheDocument();
    expect(screen.getByLabelText("Describe it.")).toBeChecked();
    expect(screen.getByLabelText("Read it.")).not.toBeChecked();
  });

  it("sends the whole grant, not the box that moved", async () => {
    // What a binding grants is what it is: a patch describing one checkbox
    // could not say "and nothing else".
    serve(
      [
        exposure({
          available_tools: [
            { id: "get_channel_info", name: "get_channel_info", description: "Describe it." },
            { id: "read_channel_history", name: "read_channel_history", description: "Read it." },
          ],
          tools: ["get_channel_info"],
        }),
      ],
      [],
    );
    await mount();

    await userEvent.click(await screen.findByLabelText("Read it."));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      tools: ["get_channel_info", "read_channel_history"],
    });
  });

  it("takes a lookup away without touching the others", async () => {
    serve(
      [
        exposure({
          available_tools: [
            { id: "get_channel_info", name: "get_channel_info", description: "Describe it." },
            { id: "read_channel_history", name: "read_channel_history", description: "Read it." },
          ],
          tools: ["get_channel_info", "read_channel_history"],
        }),
      ],
      [],
    );
    await mount();

    await userEvent.click(await screen.findByLabelText("Read it."));

    expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
      tools: ["get_channel_info"],
    });
  });

  it("is where cost reporting is chosen, per binding", async () => {
    // It moved off the Channels page: whether a reply says what the turn cost
    // is part of what this agent says on this surface, and on the bot it was an
    // operator's setting in a table of servers and tokens.
    serve([exposure()], []);
    vi.mocked(apiClient.patch).mockResolvedValue(exposure());
    await mount();

    await userEvent.click(await screen.findByRole("combobox", { name: "Cost reporting" }));
    await userEvent.click(await screen.findByRole("option", { name: "Cost: on every reply" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/agents/${AGENT_ID}/exposures/e1`, {
        usage_reporting: { mode: "always", near_limit_percent: 80, every_n: 10 },
      }),
    );
  });

  it("offers nothing where the platform answers nothing", async () => {
    // A checkbox whose only effect is a tool that refuses is worse than none.
    serve([exposure({ available_tools: [] })], []);
    await mount();

    await screen.findByText(/Acme Support/);
    expect(screen.queryByText(/What this agent may look up/)).toBeNull();
  });

  it("shows a placeholder while the bindings are being fetched", () => {
    serve([], []);
    render(<ExposuresPanel agentId={AGENT_ID} canManage hasWorkspace />, { wrapper });

    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});
