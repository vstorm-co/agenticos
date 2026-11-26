import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChannelsPage from "./page";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { Agent } from "@/types/agents";
import type { BotAgent, ChannelBot } from "@/types/channels";
import { Perm } from "@/types/permissions";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

const permissions = {
  can: vi.fn((_permission: string) => true),
  isLoading: false,
  error: null as Error | null,
  refetch: vi.fn(),
};
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => permissions }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function bound(overrides: Partial<BotAgent> = {}): BotAgent {
  return {
    exposure_id: "e1",
    is_active: true,
    id: "a1",
    name: "Support",
    slug: "support",
    has_avatar: false,
    ...overrides,
  };
}

function bot(agents: BotAgent[] = []): ChannelBot {
  return {
    id: "b1",
    platform: "slack",
    name: "Acme Support",
    is_active: true,
    webhook_mode: false,
    webhook_url: null,
    api_base_url: null,
    access_policy: {
      mode: "open",
      whitelist: [],
      allowed_groups: [],
      require_link: false,
      rate_limit_rpm: 10,
      denied_message: "Denied",
    },
    has_webhook_secret: false,
    has_slack_signing_secret: false,
    has_slack_app_token: true,
    has_command_token: false,
    command_url: null,
    ack_reaction: null,
    stream_answers: true,
    step_display: "timeline",
    rate_answers: true,
    connection: null,
    transcribe_voice_notes: true,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    agents,
    created_at: "2026-08-09T18:00:00Z",
  };
}

function agent(id: string, slug: string, overrides: Partial<Agent> = {}): Agent {
  return {
    id,
    slug,
    name: slug.charAt(0).toUpperCase() + slug.slice(1),
    description: null,
    status: "published",
    visibility: "private",
    owner_user_id: null,
    current_version_id: "v1",
    has_avatar: false,
    can_publish: true,
    ...overrides,
  } as Agent;
}

/** By URL, since the page reads the bots and the agents and the Agent list is asked after them. */
function serve(bots: ChannelBot[], agents: Agent[] | Error) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents") {
      if (agents instanceof Error) throw agents;
      return { items: agents, total: agents.length };
    }
    return { items: bots, total: bots.length };
  });
}

async function mount() {
  render(<ChannelsPage />, { wrapper });
  await screen.findByText("Acme Support");
}

async function choose(name: string) {
  const dialog = screen.getByRole("dialog");
  await userEvent.click(within(dialog).getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: new RegExp(name) }));
}

const BIND = { name: "Bind an agent to Acme Support" };
const UNBIND = { name: /^Unbind @support from Acme Support$/ };

beforeEach(() => {
  vi.clearAllMocks();
  permissions.can.mockImplementation(() => true);
  permissions.isLoading = false;
  permissions.error = null;
});

describe("binding an agent from the channels page", () => {
  it("offers no bind and asks for no agents with channels:manage but not agents:view", async () => {
    permissions.can.mockImplementation((permission) => permission === Perm.channelsManage);
    serve([bot()], [agent("a2", "writer")]);
    await mount();

    expect(screen.queryByRole("button", BIND)).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/agents", expect.anything());
    expect(apiClient.get).not.toHaveBeenCalledWith("/agents");
  });

  it("offers only agents the viewer may publish", async () => {
    serve(
      [bot()],
      [
        agent("a2", "writer"),
        agent("a3", "reader", { can_publish: false }),
        agent("a4", "private", { personal_model_key: true }),
        agent("a5", "retired", { status: "archived" }),
      ],
    );
    await mount();

    await userEvent.click(await screen.findByRole("button", BIND));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("combobox"));

    expect(await screen.findByRole("option", { name: /Writer/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /Reader/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Private/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Retired/ })).not.toBeInTheDocument();
  });

  it("asks for archived agents too, so a bound archived agent resolves its permission", async () => {
    serve([bot()], [agent("a2", "writer")]);
    await mount();

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/agents", {
        params: { include_archived: "true" },
      }),
    );
  });

  it("binds an agent the viewer may publish to an unbound bot on the default environment", async () => {
    serve([bot()], [agent("a2", "writer")]);
    vi.mocked(apiClient.post).mockResolvedValue({ id: "e9", channel_bot_name: "Acme Support" });
    await mount();
    const botReads = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/channels/bots").length;
    await screen.findByRole("button", BIND);
    const before = botReads();

    await userEvent.click(screen.getByRole("button", BIND));
    await choose("Writer");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Bind" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.post).toHaveBeenCalledWith("/agents/a2/exposures", { channel_bot_id: "b1" });
    expect(toast.success).toHaveBeenCalledWith("@writer now answers on Acme Support");
    await waitFor(() => expect(botReads()).toBeGreaterThan(before));
  });

  it("says there is no agent to bind rather than showing an empty picker", async () => {
    serve([bot()], [agent("a3", "reader", { can_publish: false })]);
    await mount();

    await userEvent.click(await screen.findByRole("button", BIND));

    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText("There is no agent you may publish to bind here."),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Bind" })).toBeDisabled();
  });

  it("shows a failed agents read instead of saying there is no agent", async () => {
    serve([bot()], new ApiError(502, "agents unavailable"));
    await mount();

    await userEvent.click(await screen.findByRole("button", BIND));

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toBeVisible();
    expect(within(dialog).queryByText(/no agent you may publish/)).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Bind" })).toBeDisabled();
  });

  it("keeps the bind dialog open and shows the refusal, then reads the bots again", async () => {
    serve([bot()], [agent("a2", "writer")]);
    const refusal = new ApiError(409, "Acme Support already serves another agent.");
    vi.mocked(apiClient.post).mockRejectedValue(refusal);
    await mount();
    const botReads = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/channels/bots").length;
    await screen.findByRole("button", BIND);
    const before = botReads();

    await userEvent.click(screen.getByRole("button", BIND));
    await choose("Writer");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Bind" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Acme Support already serves another agent."),
    );
    expect(screen.getByRole("dialog")).toBeVisible();
    await waitFor(() => expect(botReads()).toBeGreaterThan(before));
  });

  it("does not re-read the bots after a refusal that is not a conflict", async () => {
    serve([bot()], [agent("a2", "writer")]);
    vi.mocked(apiClient.post).mockRejectedValue(new ApiError(404, "Agent not found"));
    await mount();
    const botReads = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/channels/bots").length;
    await screen.findByRole("button", BIND);
    const before = botReads();

    await userEvent.click(screen.getByRole("button", BIND));
    await choose("Writer");
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Bind" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(botReads()).toBe(before);
  });

  it("lists a paused binding as paused and offers no bind on its bot", async () => {
    serve([bot([bound({ is_active: false })])], [agent("a1", "support")]);
    await mount();

    expect(await screen.findByText("Binding paused")).toBeVisible();
    expect(screen.queryByRole("button", BIND)).not.toBeInTheDocument();
  });

  it("links the agent to its Availability tab", async () => {
    serve([bot([bound()])], [agent("a1", "support")]);
    await mount();

    expect(await screen.findByRole("link", { name: "@support" })).toHaveAttribute(
      "href",
      "/agents/a1?tab=availability",
    );
  });
});

describe("unbinding an agent from the channels page", () => {
  it("unbinds only after confirmation, by the binding's own id", async () => {
    serve([bot([bound()])], [agent("a1", "support")]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await userEvent.click(await screen.findByRole("button", UNBIND));
    expect(apiClient.delete).not.toHaveBeenCalled();
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Unbind" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1/exposures/e1");
    expect(toast.success).toHaveBeenCalledWith("@support no longer answers on Acme Support");
  });

  it("leaves the binding alone when the confirmation is cancelled", async () => {
    serve([bot([bound()])], [agent("a1", "support")]);
    await mount();

    await userEvent.click(await screen.findByRole("button", UNBIND));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it.each([
    ["an agent the viewer may not publish", [agent("a1", "support", { can_publish: false })]],
    ["an agent missing from the viewer's list", [agent("a9", "other")]],
  ])("shows %s without an unbind control", async (_label, agents) => {
    serve([bot([bound()])], agents);
    await mount();

    expect(await screen.findByText("@support")).toBeVisible();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/agents", expect.anything()));
    expect(screen.queryByRole("button", { name: /Unbind/ })).not.toBeInTheDocument();
  });

  it("reserves the unbind button's slot while the agents are still being read", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/agents") return new Promise(() => {});
      return { items: [bot([bound()])], total: 1 };
    });
    await mount();

    expect(await screen.findByTestId("unbind-slot")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Unbind/ })).not.toBeInTheDocument();
  });

  it("shows no unbind control when the agents read failed", async () => {
    serve([bot([bound()])], new ApiError(502, "agents unavailable"));
    await mount();

    expect(await screen.findByText("@support")).toBeVisible();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/agents", expect.anything()));
    expect(screen.queryByRole("button", { name: /Unbind/ })).not.toBeInTheDocument();
  });

  it("still unbinds an archived agent the viewer may publish", async () => {
    serve([bot([bound()])], [agent("a1", "support", { status: "archived" })]);
    await mount();

    expect(await screen.findByRole("button", UNBIND)).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/agents", {
      params: { include_archived: "true" },
    });
  });

  it("keeps unbind open after a refusal and allows a retry", async () => {
    serve([bot([bound()])], [agent("a1", "support")]);
    vi.mocked(apiClient.delete)
      .mockRejectedValueOnce(new ApiError(404, "Not found"))
      .mockResolvedValueOnce(undefined);
    await mount();

    await userEvent.click(await screen.findByRole("button", UNBIND));
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "Unbind" });
    await userEvent.click(confirm);

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Not found"));
    expect(screen.getByRole("dialog")).toBeVisible();
    await userEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.delete).toHaveBeenCalledTimes(2);
  });
});
