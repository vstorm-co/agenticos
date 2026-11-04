import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelBotsTable } from "./channel-bots-table";
import { DiscordRoleMappingsDialog } from "./discord-role-mappings-dialog";
import { apiClient, ApiError } from "@/lib/api-client";
import { useOrgStore } from "@/stores";
import type { ChannelBot, DiscordRoleMapping } from "@/types/channels";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// The caller's authority: `members:manage` opens the dialog at all, `roles:manage`
// and the roles their own outranks decide what it offers and what it may delete.
let mayAssignRoles = false;
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (perm: string) => perm !== "roles:manage" || mayAssignRoles,
    isLoading: false,
    role: "admin",
  }),
  useAssignableRoles: () => ["builder", "operator", "member", "viewer"],
}));

const SERVERS = [
  {
    id: "1100",
    name: "Acme HQ",
    roles: [
      { id: "7", name: "Finance" },
      { id: "8", name: "Support" },
    ],
  },
];

function mapping(overrides: Partial<DiscordRoleMapping> = {}): DiscordRoleMapping {
  return {
    id: "m-1",
    channel_bot_id: "b-1",
    guild_id: "1100",
    guild_name: "Acme HQ",
    discord_role_id: "7",
    discord_role_name: "Finance",
    group_id: "g-1",
    group_name: "Finance team",
    role: null,
    created_at: "2026-11-01T00:00:00Z",
    ...overrides,
  };
}

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b-1",
    platform: "discord",
    name: "Helper",
    is_active: true,
    agents: [],
    ...overrides,
  } as ChannelBot;
}

let mappings: DiscordRoleMapping[] = [];
let serversAnswer: () => Promise<unknown> = async () => ({ items: SERVERS, total: 1 });

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  mayAssignRoles = false;
  mappings = [];
  serversAnswer = async () => ({ items: SERVERS, total: 1 });
  useOrgStore.setState({ activeOrgId: "o-1" });
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/channels/bots/b-1/role-mappings")
      return { items: mappings, total: mappings.length };
    if (path === "/channels/bots/b-1/discord-servers") return serversAnswer();
    if (path === "/orgs/o-1/groups") {
      return { items: [{ id: "g-1", name: "Finance team" }], total: 1 };
    }
    throw new Error(`unexpected GET ${path}`);
  });
});

async function choose(user: ReturnType<typeof userEvent.setup>, field: string, option: string) {
  await user.click(screen.getByRole("combobox", { name: field }));
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("the bots table", () => {
  it("offers role mappings on a Discord bot, to somebody who may manage members", () => {
    const onMapRoles = vi.fn();
    const handlers = { onEdit: vi.fn(), onToggleActive: vi.fn(), onDelete: vi.fn() };
    const bots = [bot(), bot({ id: "b-2", platform: "slack", name: "Slacker" })];
    const { rerender } = render(
      <ChannelBotsTable bots={bots} busy={false} {...handlers} onMapRoles={onMapRoles} />,
    );

    expect(screen.getAllByRole("button", { name: /Discord roles for/ })).toHaveLength(1);
    screen.getByRole("button", { name: "Discord roles for Helper" }).click();
    expect(onMapRoles).toHaveBeenCalledWith(bots[0]);

    // The page passes no handler to somebody without `members:manage`.
    rerender(<ChannelBotsTable bots={bots} busy={false} {...handlers} />);
    expect(screen.queryByRole("button", { name: /Discord roles for/ })).toBeNull();
  });
});

describe("the role mappings dialog", () => {
  it("maps a server role to a group, placing existing members only", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(mapping());
    render(<DiscordRoleMappingsDialog bot={bot()} onClose={vi.fn()} />, { wrapper });
    expect(await screen.findByText("No roles mapped yet.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Map a role" }));
    // Without `roles:manage` the mapping can only place people already here.
    expect(screen.queryByRole("combobox", { name: "Admit as" })).toBeNull();
    await choose(user, "Server", "Acme HQ");
    await choose(user, "Discord role", "@Support");
    await choose(user, "Group", "Finance team");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b-1/role-mappings", {
        guild_id: "1100",
        discord_role_id: "8",
        group_id: "g-1",
        role: null,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: "Add" })).toBeNull());
  });

  it("admits with a role only from the roles the caller's own outranks", async () => {
    mayAssignRoles = true;
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockResolvedValue(mapping({ role: "member" }));
    render(<DiscordRoleMappingsDialog bot={bot()} onClose={vi.fn()} />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Map a role" }));
    await user.click(screen.getByRole("combobox", { name: "Admit as" }));
    expect(screen.queryByRole("option", { name: "admin" })).toBeNull();
    await user.click(screen.getByRole("option", { name: "member" }));
    await choose(user, "Server", "Acme HQ");
    await choose(user, "Discord role", "@Finance");
    await choose(user, "Group", "Finance team");
    expect(screen.getByText(/joins this organization with the role above/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/channels/bots/b-1/role-mappings",
        expect.objectContaining({ role: "member" }),
      ),
    );
  });

  it("shows a refused role under the field it came from", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "That Discord role is already mapped for this bot"),
    );
    render(<DiscordRoleMappingsDialog bot={bot()} onClose={vi.fn()} />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Map a role" }));
    await choose(user, "Server", "Acme HQ");
    await choose(user, "Discord role", "@Finance");
    await choose(user, "Group", "Finance team");
    await user.click(screen.getByRole("button", { name: "Add" }));

    expect(
      await screen.findByText("That Discord role is already mapped for this bot"),
    ).toBeInTheDocument();
  });

  it("says so when Discord does not answer, rather than offering no servers", async () => {
    const user = userEvent.setup();
    serversAnswer = async () => {
      throw new ApiError(
        503,
        "Discord did not say which servers and roles the bot can see. Try again.",
      );
    };
    render(<DiscordRoleMappingsDialog bot={bot()} onClose={vi.fn()} />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Map a role" }));

    expect(await screen.findByText(/Discord did not say which servers/)).toBeInTheDocument();
  });

  it("deletes only the mappings the caller could have made", async () => {
    const user = userEvent.setup();
    mappings = [
      mapping(),
      mapping({ id: "m-2", discord_role_id: "8", discord_role_name: "Support", role: "member" }),
    ];
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    render(<DiscordRoleMappingsDialog bot={bot()} onClose={vi.fn()} />, { wrapper });

    expect(await screen.findByText("Acme HQ · @Finance → Finance team")).toBeInTheDocument();
    // Admitting as `member` takes `roles:manage` to undo, which this caller lacks.
    expect(screen.queryByRole("button", { name: "Delete the mapping for @Support" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Delete the mapping for @Finance" }));
    const confirm = await screen.findByRole("dialog", { name: "Delete this mapping?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/channels/bots/b-1/role-mappings/m-1"),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Delete this mapping?" })).toBeNull(),
    );
  });
});
