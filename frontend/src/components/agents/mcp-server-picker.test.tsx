import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { bindingKey, McpServerPicker } from "./mcp-server-picker";
import { NEW_PLATFORM_BINDING } from "./platform-server-card";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { McpServerRef, OrgMcpServerRef, PersonalMcpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";

vi.mock("@/hooks", async (original) => ({
  ...(await original<typeof import("@/hooks")>()),
  usePlatformMcpTools: () => ({ tools: [], isLoading: false, error: null }),
}));

function entry(overrides: Partial<McpCatalogEntry> = {}): McpCatalogEntry {
  return { ...GITHUB, ...overrides };
}

const GITHUB: McpCatalogEntry = {
  key: "github",
  name: "GitHub",
  description: "Read issues and pull requests.",
  category: "development",
  auth: "token",
  url: "https://api.githubcopilot.com/mcp/",
  docs_url: null,
  token_hint: null,
  icon: null,
};

const CATALOG: McpCatalogEntry[] = [GITHUB];

function connection(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "c1",
    name: "gh",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    include_instructions: false,
    auth_type: "bearer",
    oauth_authorized: false,
    authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    visibility: "org",
    catalog_key: null,
    is_default: false,
    label: null,
    last_tools: null,
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** A binding to the organization's connection - what ticking a row writes. */
function bound(connectionId: string, tools: string[] | null = null): OrgMcpServerRef {
  return {
    account: "organization",
    connection_id: connectionId,
    allowed_tools: tools,
    approval: "none",
  };
}

/** A binding to each person's own account on a catalog service. */
function personal(catalogKey: string, tools: string[] | null = null): PersonalMcpServerRef {
  return { account: "personal", catalog_key: catalogKey, allowed_tools: tools, approval: "none" };
}

function picker(props: {
  connections?: OrgMcpConnectionRecord[];
  catalog?: McpCatalogEntry[];
  value?: McpServerRef[];
  onChange?: (next: McpServerRef[]) => void;
  onTools?: (ref: McpServerRef, probed: OrgMcpConnectionRecord, name: string) => void;
  onConnect?: (entry: McpCatalogEntry) => void;
  disabled?: boolean;
}) {
  return (
    <McpServerPicker
      connections={props.connections ?? []}
      catalog={props.catalog ?? CATALOG}
      value={props.value ?? []}
      onChange={props.onChange ?? vi.fn()}
      onTools={props.onTools ?? vi.fn()}
      onConnect={props.onConnect ?? vi.fn()}
      disabled={props.disabled}
    />
  );
}

/** One of the two answers to "whose account", as a tile in the settings. */
const kind = (which: "organization" | "personal") =>
  screen.getByRole("radio", {
    name: which === "organization" ? /^The organization's account/ : /^Each person's own account/,
  });

/** Open a server's settings the way a person does: by clicking its card. */
async function settings(description = GITHUB.description) {
  await userEvent.click(screen.getByText(description));
  return screen.findByRole("dialog");
}

describe("McpServerPicker", () => {
  it("names a connection after the catalog server it points at", () => {
    // The connection is called "gh" because the name is a tool prefix. Nobody
    // building an agent is looking for "gh".
    render(picker({ connections: [connection()] }));

    expect(screen.getByRole("switch", { name: "Use GitHub in this agent" })).toBeInTheDocument();
    // How it signs in is the servers page's business, not a question here.
    expect(screen.queryByText("API token")).toBeNull();
  });

  it("falls back to the connection's own name for a server not in the catalog", () => {
    render(
      picker({
        connections: [connection({ name: "internal-crm", url: "https://crm.internal/mcp" })],
      }),
    );

    expect(
      screen.getByRole("switch", { name: "Use internal-crm in this agent" }),
    ).toBeInTheDocument();
  });

  it("reflects what the spec already references", () => {
    render(
      picker({
        connections: [
          connection(),
          connection({ id: "c2", name: "linear", url: "https://mcp.linear.app/sse" }),
        ],
        value: [bound("c1")],
      }),
    );

    expect(screen.getByRole("switch", { name: "Use GitHub in this agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("switch", { name: "Use linear in this agent" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("draws no account status or catalog check on the card", () => {
    // Whether an account answered a probe is the servers page's to say; on the
    // card it was noise between somebody and the switch they came for.
    render(
      picker({
        connections: [connection({ last_status: "error", catalog_key: "github" })],
        catalog: [
          {
            ...GITHUB,
            check: { outcome: "unreachable", checked_at: "2026-10-12T00:00:00Z" },
          } as McpCatalogEntry,
        ],
      }),
    );

    expect(screen.queryByText("Unreachable")).toBeNull();
    expect(screen.queryByText(/Checked/)).toBeNull();
  });

  it("binds the connection whose switch was turned on", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], onChange }));

    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("offers this platform's own server first, and binds it beside the others", async () => {
    const onChange = vi.fn();
    const { unmount } = render(
      picker({ connections: [connection()], value: [bound("c1")], onChange }),
    );
    const [first] = screen.getAllByRole("group");
    expect(within(first as HTMLElement).getByText("Built in")).toBeInTheDocument();

    await userEvent.click(within(first as HTMLElement).getByRole("switch"));
    expect(onChange).toHaveBeenLastCalledWith([bound("c1"), NEW_PLATFORM_BINDING]);
    unmount();

    render(
      picker({ connections: [connection()], value: [NEW_PLATFORM_BINDING, bound("c1")], onChange }),
    );
    await userEvent.click(
      within(screen.getAllByRole("group")[0] as HTMLElement).getByRole("switch"),
    );
    expect(onChange).toHaveBeenLastCalledWith([bound("c1")]);
  });

  it("lets a search rule out the built-in server as it rules out the others", async () => {
    render(picker({ connections: [connection()], value: [], onChange: vi.fn() }));
    expect(screen.getByText("Built in")).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Search servers…"), "github");
    expect(screen.queryByText("Built in")).toBeNull();
    expect(screen.getByText("GitHub")).toBeInTheDocument();
  });

  it("drops a binding rather than writing it twice", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], value: [bound("c1")], onChange }));

    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("is operable from the keyboard", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], onChange }));

    screen.getByRole("switch", { name: "Use GitHub in this agent" }).focus();
    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("ignores interaction when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], onChange, disabled: true }));

    const target = screen.getByRole("switch", { name: "Use GitHub in this agent" });
    await userEvent.click(target);
    target.focus();
    await userEvent.keyboard("{Enter}");

    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows spec references it cannot resolve instead of dropping them", () => {
    // An imported spec can name a server this organization does not have. If
    // the picker rendered nothing the next save would silently delete it, and
    // the publish refusal would name an id nothing on screen explains.
    render(
      picker({
        connections: [connection()],
        value: [bound("c1"), bound("00000000-0000-0000-0000-0000000000ff")],
      }),
    );

    expect(screen.getByText(/1 server this organization does not offer/)).toBeInTheDocument();
    expect(screen.getByText("00000000-0000-0000-0000-0000000000ff")).toBeInTheDocument();
  });

  it("counts more than one unresolved reference in the plural", () => {
    render(picker({ connections: [connection()], value: [bound("gone-1"), bound("gone-2")] }));

    expect(screen.getByText(/2 servers this organization does not offer/)).toBeInTheDocument();
  });

  it("does not count a binding to each person's own account as unresolved", () => {
    // It names a service, not a connection, so there is no id to be missing.
    render(picker({ value: [personal("github")] }));

    expect(screen.queryByText(/does not offer/)).toBeNull();
  });

  it("never counts the platform's own server as unresolved", () => {
    // It is this deployment, so there is nothing that can have gone.
    render(picker({ value: [{ account: "platform", allowed_tools: null, approval: "writes" }] }));

    expect(screen.queryByText(/does not offer/)).toBeNull();
  });

  it("shows a personal binding to a key the catalog no longer describes", () => {
    // No card can match it, so unlisted it would vanish from the Builder while
    // publish kept refusing the unknown key.
    render(picker({ value: [personal("gone-server")] }));

    expect(screen.getByText(/1 server this organization does not offer/)).toBeInTheDocument();
    expect(screen.getByText("gone-server")).toBeInTheDocument();
  });

  it("shows the whole catalog, not only what already has credentials", () => {
    // "What can I attach right now" was answerable; "what could this agent
    // reach at all" needed another page, and a catalog nobody sees is a catalog
    // nobody connects from.
    render(picker({}));

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("offers to connect an unconnected server here rather than sending anyone away", async () => {
    // It used to be a link to `/mcp-servers`, which threw away an unsaved draft
    // and asked somebody to find their way back to the agent they were editing.
    const onConnect = vi.fn();
    render(picker({ onConnect }));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await settings();
    await userEvent.click(kind("organization"));
    await userEvent.click(screen.getByRole("button", { name: "Connect for the organization" }));

    // The entry, so the caller's dialog can seed a form from it.
    expect(onConnect).toHaveBeenCalledWith(GITHUB);
  });

  it("an unconnected server is not a checkbox, because there is no id to bind", () => {
    // The spec stores connection ids; a catalog entry has none. A checkbox here
    // would be one that cannot write anything.
    render(picker({}));

    expect(screen.queryByRole("checkbox", { name: "GitHub" })).not.toBeInTheDocument();
  });

  it("hides the servers nobody connected when asked, which is most of the catalog", async () => {
    // Only a connected server can be bound to the organization's account. The
    // rest are shown to advertise, and sixty of them buries the two that can
    // actually be picked.
    const linear = entry({ key: "linear", name: "Linear" });
    render(
      picker({
        connections: [connection({ catalog_key: "github" })],
        catalog: [...CATALOG, linear],
      }),
    );

    await userEvent.click(screen.getByRole("checkbox", { name: "Connected only" }));

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByText("Linear")).toBeNull();
  });

  it("searches names and descriptions, not just names", async () => {
    // Somebody looking for issue tracking does not know the product is called
    // Linear - and this picker shows sixty cards.
    const linear = entry({
      key: "linear",
      name: "Linear",
      description: "Search and update issues.",
    });
    render(picker({ catalog: [...CATALOG, linear] }));

    await userEvent.type(screen.getByLabelText("Search servers…"), "pull requests");

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByText("Linear")).toBeNull();
  });
});

describe("several connections behind one catalog entry", () => {
  /**
   * Five Notion servers with five credentials and five sets of permissions is a
   * shape the schema allows - uniqueness is `(organization_id, name)`, and the
   * name is the tool prefix. The picker used to key its rows on the catalog
   * entry, so four of the five vanished (#1341); keying on the connection
   * instead brought them all back as five cards saying "Notion", which is the
   * same catalog read five times.
   */
  const THREE = [
    connection({ id: "c1", name: "gh-readonly", catalog_key: "github" }),
    connection({ id: "c2", name: "gh-issues", catalog_key: "github" }),
    connection({ id: "c3", name: "gh-admin", catalog_key: "github" }),
  ];

  it("shows one row for the server and offers its accounts in a select", async () => {
    render(picker({ connections: THREE, value: [bound("c1")] }));

    expect(screen.getAllByText("GitHub")).toHaveLength(1);
    await settings();
    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    for (const name of ["gh-readonly", "gh-issues", "gh-admin"]) {
      expect(await screen.findByRole("option", { name })).toBeVisible();
    }
  });

  it("shows the bound account rather than the first, so the row says which is in use", async () => {
    render(picker({ connections: THREE, value: [bound("c3")] }));
    expect(screen.getByRole("switch", { name: "Use GitHub in this agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await settings();

    expect(screen.getByRole("combobox", { name: /which github account/i })).toHaveTextContent(
      "gh-admin",
    );
  });

  it("replaces the bound account rather than binding a second one", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE, value: [bound("c1")], onChange }));

    await settings();
    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    await userEvent.click(await screen.findByRole("option", { name: "gh-issues" }));

    expect(onChange).toHaveBeenCalledWith([bound("c2")]);
  });

  it("binds the account the select is showing", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE, onChange }));

    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("binds the server from its settings with whose account was chosen there", async () => {
    // Choosing alone binds nothing - the switch does, with the choice on screen.
    const onChange = vi.fn();
    render(picker({ connections: THREE, onChange }));

    const dialog = await settings();
    await userEvent.click(kind("organization"));
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenLastCalledWith([bound("c1")]);
  });

  it("binds a second account of the server beside the first (#2125)", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE, value: [bound("c1")], onChange }));

    await settings();
    await userEvent.click(screen.getByRole("button", { name: "Add another account" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1"), bound("c2")]);
  });

  it("lists every bound account and offers each only the accounts still free", async () => {
    render(picker({ connections: THREE, value: [bound("c1"), bound("c3")] }));

    expect(screen.getByText("2 accounts")).toBeInTheDocument();
    await settings();
    const [first] = screen.getAllByRole("combobox", { name: /which github account/i });
    await userEvent.click(first!);

    expect(await screen.findByRole("option", { name: "gh-readonly" })).toBeVisible();
    expect(screen.getByRole("option", { name: "gh-issues" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "gh-admin" })).toBeNull();
  });

  it("moves one of several accounts to another connection, leaving the rest", async () => {
    const onChange = vi.fn();
    const labelled = [
      ...THREE,
      connection({ id: "c4", name: "gh-info", label: "info@", catalog_key: "github" }),
    ];
    render(picker({ connections: labelled, value: [bound("c1"), bound("c3")], onChange }));

    await settings();
    const [, second] = screen.getAllByRole("combobox", { name: /which github account/i });
    await userEvent.click(second!);
    await userEvent.click(await screen.findByRole("option", { name: /^info@/ }));

    expect(onChange).toHaveBeenCalledWith([bound("c1"), bound("c4")]);
  });

  it("names each bound account even when there is nothing left to switch to", async () => {
    const two = [
      connection({ id: "c1", name: "github", label: "Company", catalog_key: "github" }),
      connection({ id: "c2", name: "github-oss", catalog_key: "github" }),
    ];
    render(picker({ connections: two, value: [bound("c1"), bound("c2")] }));

    const dialog = await settings();

    expect(within(dialog).getByText("Company")).toBeVisible();
    expect(within(dialog).getAllByText("github-oss")[0]).toBeVisible();
    expect(within(dialog).queryByRole("combobox", { name: /which github account/i })).toBeNull();
  });

  it("drops one account and keeps the others", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE, value: [bound("c1"), bound("c3")], onChange }));

    await settings();
    await userEvent.click(screen.getByRole("button", { name: "Stop using this GitHub account" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("adds each person's own account once the organization's are all bound", async () => {
    const onChange = vi.fn();
    const one = [connection({ id: "c1", name: "gh", catalog_key: "github" })];
    render(picker({ connections: one, value: [bound("c1")], onChange }));

    await settings();
    await userEvent.click(screen.getByRole("button", { name: "Add another account" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1"), personal("github")]);
  });

  it("offers no further account when every one is already bound", async () => {
    const one = [connection({ id: "c1", name: "gh", catalog_key: "github" })];
    render(picker({ connections: one, value: [bound("c1"), personal("github")] }));

    await settings();
    expect(screen.queryByRole("button", { name: "Add another account" })).toBeNull();
  });

  it("switches an account between the organization's and each person's own", async () => {
    const onChange = vi.fn();
    const one = [connection({ id: "c1", name: "gh", catalog_key: "github" })];
    render(picker({ connections: one, value: [personal("github", ["read"])], onChange }));

    await settings();
    await userEvent.click(kind("organization"));

    expect(onChange).toHaveBeenCalledWith([bound("c1", ["read"])]);
  });

  it("offers no choice where there is none to make", () => {
    render(picker({ connections: [connection({ id: "c1", name: "gh", catalog_key: "github" })] }));

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /which github account/i })).toBeNull();
  });

  it("cannot be re-pointed by a viewer who cannot edit", async () => {
    render(picker({ connections: THREE, value: [bound("c1")], disabled: true }));

    await userEvent.click(screen.getByText(GITHUB.description));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Settings for GitHub/ })).toBeNull();
  });
});

describe("whose account a binding speaks through", () => {
  /**
   * A binding is one of two kinds. The organization's connection answers for
   * everybody and is the reviewable default; each person's own account names
   * the service instead, and whoever talks to the agent connects their own. The
   * second needs no connection here, so an unconnected server offers it too.
   */
  const GH = connection({ id: "c1", name: "gh", catalog_key: "github" });

  it("binds the organization's account when a connected row is switched on", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [GH], onChange }));

    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("closes its settings with Done", async () => {
    render(picker({ connections: [GH], value: [bound("c1")] }));
    await settings();

    await userEvent.click(screen.getByRole("button", { name: "Done" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("asks whose account in the settings it opens when switched on", async () => {
    render(picker({ connections: [GH] }));

    expect(screen.queryByRole("combobox", { name: /whose github account/i })).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("switches a bound server to each person's own account, keeping its tools", async () => {
    // The tools are chosen for the agent; whose credential reaches them is a
    // different question, and the server offers the same tools either way.
    const onChange = vi.fn();
    render(picker({ connections: [GH], value: [bound("c1", ["search"])], onChange }));

    await settings();
    await userEvent.click(kind("personal"));

    expect(onChange).toHaveBeenCalledWith([personal("github", ["search"])]);
  });

  it("switches back to the organization's account, keeping its tools", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [GH], value: [personal("github", ["search"])], onChange }));

    await settings();
    await userEvent.click(kind("organization"));

    expect(onChange).toHaveBeenCalledWith([bound("c1", ["search"])]);
  });

  it("leaves a server off while whose account it would use is chosen", async () => {
    // Going to the organization's account and back used to switch the server
    // on by itself: choosing whose account bound it.
    const onChange = vi.fn();
    render(picker({ connections: [GH], onChange }));

    await settings();
    await userEvent.click(kind("personal"));
    await userEvent.click(kind("organization"));
    await userEvent.click(kind("personal"));

    expect(onChange).not.toHaveBeenCalled();
    expect(kind("personal")).toHaveAttribute("aria-checked", "true");
  });

  it("switches on in the settings with the account chosen there", async () => {
    // The card's own switch prefers the organization's account; from the
    // settings, the choice already on screen is the one that is meant.
    const onChange = vi.fn();
    render(picker({ connections: [GH], onChange }));

    const dialog = await settings();
    await userEvent.click(kind("personal"));
    await userEvent.click(within(dialog).getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([personal("github")]);
  });

  it("switches on in the settings with the organization's account when that is chosen", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [GH], onChange }));

    const dialog = await settings();
    await userEvent.click(kind("personal"));
    await userEvent.click(kind("organization"));
    await userEvent.click(within(dialog).getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("changes nothing when the account already in use is chosen again", async () => {
    const onChange = vi.fn();
    const { unmount } = render(picker({ connections: [GH], value: [bound("c1")], onChange }));
    await settings();
    await userEvent.click(kind("organization"));
    unmount();

    render(picker({ connections: [GH], value: [personal("github")], onChange }));
    await settings();
    await userEvent.click(kind("personal"));

    expect(onChange).not.toHaveBeenCalled();
  });

  it("switches on with each person's own account when the organization has none to give", async () => {
    // The organization's tile was chosen, but there is no account to bind yet;
    // the switch falls back to what the card's own switch would do.
    const onChange = vi.fn();
    render(picker({ onChange }));

    const dialog = await settings();
    await userEvent.click(kind("organization"));
    await userEvent.click(within(dialog).getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([personal("github")]);
  });

  it("switches off from the settings whatever account was chosen", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [GH], value: [bound("c1")], onChange }));

    const dialog = await settings();
    await userEvent.click(kind("organization"));
    await userEvent.click(within(dialog).getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("says on the card that each person's own account answers", async () => {
    render(picker({ connections: [GH], value: [personal("github")] }));
    expect(
      screen.getByRole("button", { name: "Settings for GitHub in this agent" }),
    ).toHaveTextContent("Each person's own account");
    expect(screen.getByRole("switch", { name: "Use GitHub in this agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await settings();

    expect(kind("personal")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/You have not connected yours yet/)).toBeInTheDocument();
  });

  it("offers each person's own account for a server nobody has connected", async () => {
    // The binding names the service, so it needs no connection to exist - the
    // whole point of the kind is that each person brings their own.
    const onChange = vi.fn();
    render(picker({ onChange }));

    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([personal("github")]);
  });

  it("connects the organization's account in one step from its own choice", async () => {
    // Choosing it with none connected is connecting one, not a second button
    // under the choice.
    const onConnect = vi.fn();
    const onChange = vi.fn();
    render(picker({ onConnect, onChange, value: [personal("github")] }));

    await settings();
    await userEvent.click(kind("organization"));
    // Nothing to bind yet: the binding stays until there is an account.
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Connect for the organization" }));

    expect(onConnect).toHaveBeenCalledWith(GITHUB);
  });

  it("offers to connect your own account under each person's own, where you have none", async () => {
    const onConnectOwn = vi.fn();
    render(
      <McpServerPicker
        connections={[]}
        catalog={CATALOG}
        value={[personal("github")]}
        onChange={vi.fn()}
        onTools={vi.fn()}
        onConnect={vi.fn()}
        onConnectOwn={onConnectOwn}
      />,
    );

    await settings();
    await userEvent.click(screen.getByRole("button", { name: "Connect yours" }));

    expect(onConnectOwn).toHaveBeenCalledWith(GITHUB);
  });

  describe("Configure, for a server whose Connect signs straight in", () => {
    const NOTION = entry({ key: "notion", name: "Notion", auth: "oauth", description: "Pages." });
    const mount = (
      onConfigure: (e: McpCatalogEntry, scope: string) => void,
      value: McpServerRef[] = [],
    ) =>
      render(
        <McpServerPicker
          connections={[]}
          catalog={[NOTION]}
          value={value}
          onChange={vi.fn()}
          onTools={vi.fn()}
          onConnect={vi.fn()}
          onConnectOwn={vi.fn()}
          onConfigure={onConfigure}
        />,
      );

    it("sits under the organization's tile while it holds no account", async () => {
      const onConfigure = vi.fn();
      mount(onConfigure, [personal("notion")]);

      await settings("Pages.");
      await userEvent.click(kind("organization"));
      await userEvent.click(screen.getByRole("button", { name: "Configure" }));

      expect(onConfigure).toHaveBeenCalledWith(NOTION, "organization");
    });

    it("sits beside Connect yours", async () => {
      const onConfigure = vi.fn();
      mount(onConfigure, [personal("notion")]);

      await settings("Pages.");
      await userEvent.click(screen.getByRole("button", { name: "Configure" }));

      expect(onConfigure).toHaveBeenCalledWith(NOTION, "personal");
    });

    it("is not offered for a server that takes a token", () => {
      render(picker({}));

      expect(screen.queryByRole("button", { name: /^Configure/ })).toBeNull();
    });
  });

  it("renders a personal binding on an unconnected server as a bound card", () => {
    render(picker({ value: [personal("github")] }));

    expect(screen.getByRole("switch", { name: "Use GitHub in this agent" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.queryByRole("option", { name: "The organization's account" })).toBeNull();
  });

  it("unbinds a personal binding when its switch is turned off", async () => {
    const onChange = vi.fn();
    render(picker({ value: [personal("github")], onChange }));

    await userEvent.click(screen.getByRole("switch", { name: "Use GitHub in this agent" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("leaves the other bindings alone", async () => {
    const other = connection({ id: "c9", name: "linear", url: "https://mcp.linear.app/sse" });
    const onChange = vi.fn();
    render(picker({ connections: [GH, other], value: [bound("c9"), bound("c1")], onChange }));

    await settings();
    await userEvent.click(kind("personal"));

    expect(onChange).toHaveBeenCalledWith([bound("c9"), personal("github")]);
  });

  it("does not offer each person's own account for a server outside the catalog", async () => {
    // A custom URL has no catalog key for anybody's own connection to be
    // matched on, so only the organization's connection can be bound.
    render(
      picker({
        connections: [connection({ id: "c1", name: "crm", url: "https://crm.internal/mcp" })],
        value: [bound("c1")],
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Settings for crm in this agent" }));

    expect(kind("organization")).toHaveAttribute("aria-checked", "true");
    expect(kind("personal")).toBeDisabled();
  });

  it("cannot be switched by a viewer who cannot edit", () => {
    render(picker({ connections: [GH], value: [bound("c1")], disabled: true }));

    expect(screen.getByRole("switch", { name: "Use GitHub in this agent" })).toBeDisabled();
  });
});

describe("which of a server's tools this agent may call", () => {
  /**
   * `allowed_tools` used to live only on the connection, so two agents bound to
   * one server got the same tools and the picker said so in its own docstring.
   * It is on the binding now, and the two intersect at run time - the
   * connection's list is an administrator's ceiling (#1341).
   */
  const GH = connection({ id: "c1", name: "gh", catalog_key: "github" });

  it("is not offered until the server is bound", () => {
    render(picker({ connections: [GH] }));

    expect(screen.queryByRole("button", { name: /tool/i })).not.toBeInTheDocument();
  });

  const TOOLS = [
    { name: "search", description: "Search code" },
    { name: "fetch", description: "Read a file" },
    { name: "create_issue", description: "Open an issue" },
  ];

  it("ticks every tool while the binding narrows nothing", async () => {
    render(picker({ connections: [{ ...GH, last_tools: TOOLS }], value: [bound("c1")] }));
    await settings();

    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "fetch" })).toBeChecked();
  });

  it("narrows to the rest when a tool is unticked, and back to every tool", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [{ ...GH, last_tools: TOOLS }], value: [bound("c1")], onChange }));
    await settings();

    await userEvent.click(screen.getByRole("checkbox", { name: "fetch" }));
    expect(onChange).toHaveBeenLastCalledWith([bound("c1", ["search", "create_issue"])]);
  });

  it("selects every tool again, which means every tool rather than a list", async () => {
    const onChange = vi.fn();
    render(
      picker({
        connections: [{ ...GH, last_tools: TOOLS }],
        value: [bound("c1", ["search"])],
        onChange,
      }),
    );
    await settings();

    expect(screen.getByText("1 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Every tool in Tools" }));
    expect(onChange).toHaveBeenLastCalledWith([bound("c1")]);
  });

  it("asks the caller to load the tools of an account never checked", async () => {
    const onTools = vi.fn();
    render(picker({ connections: [GH], value: [bound("c1", ["search"])], onTools }));

    await settings();
    await userEvent.click(screen.getByRole("button", { name: "Load its tools" }));

    expect(onTools).toHaveBeenCalledWith(bound("c1", ["search"]), GH, "GitHub");
  });

  it("lists a personal binding's tools from the reader's own account", async () => {
    render(
      <McpServerPicker
        connections={[]}
        catalog={CATALOG}
        value={[personal("github")]}
        onChange={vi.fn()}
        onTools={vi.fn()}
        onConnect={vi.fn()}
        personalConnections={[
          { ...connection({ catalog_key: "github" }), last_tools: TOOLS } as never,
        ]}
      />,
    );
    await settings();

    expect(screen.getByText("3 of 3")).toBeInTheDocument();
  });

  it("says where the tools come from when nothing has listed them", async () => {
    render(picker({ value: [personal("github")] }));
    await settings();

    expect(
      screen.getByText("Its tools are listed once a GitHub account is connected."),
    ).toBeInTheDocument();
  });

  it("carries the choice across a change of account", async () => {
    const onChange = vi.fn();
    const two = [
      connection({ id: "c1", name: "gh-work", catalog_key: "github" }),
      connection({ id: "c2", name: "gh-side", catalog_key: "github" }),
    ];
    render(picker({ connections: two, value: [bound("c1", ["search"])], onChange }));

    await settings();
    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    await userEvent.click(await screen.findByRole("option", { name: "gh-side" }));

    expect(onChange).toHaveBeenCalledWith([bound("c2", ["search"])]);
  });

  it("cannot be opened by a viewer who cannot edit", async () => {
    render(picker({ connections: [GH], value: [bound("c1")], disabled: true }));

    await userEvent.click(screen.getByText(GITHUB.description));

    expect(screen.queryByRole("checkbox", { name: "search" })).toBeNull();
  });
});

describe("a server's settings", () => {
  const NOTION = entry({ key: "notion", name: "Notion", auth: "oauth", description: "Pages." });
  const READS = [
    { name: "notion-search", description: "Search", read_only: true },
    { name: "notion-create-pages", description: "Create" },
  ];
  const mine = (count: number) =>
    Array.from(
      { length: count },
      (_, i) =>
        ({
          ...connection({ id: `p${i}`, name: `notion-${i}`, catalog_key: "notion" }),
          last_tools: READS,
        }) as never,
    );
  const mount = (
    props: Partial<{
      value: McpServerRef[];
      onChange: (next: McpServerRef[]) => void;
      onConnectOwn: (entry: McpCatalogEntry) => void;
      own: number;
    }> = {},
  ) =>
    render(
      <McpServerPicker
        connections={[]}
        catalog={[NOTION]}
        value={props.value ?? []}
        onChange={props.onChange ?? vi.fn()}
        onTools={vi.fn()}
        onConnect={vi.fn()}
        onConnectOwn={props.onConnectOwn}
        personalConnections={mine(props.own ?? 1)}
      />,
    );

  it("previews the tools of a server not yet used, and switches it on from the header", async () => {
    const onChange = vi.fn();
    mount({ onChange });

    await settings("Pages.");
    // What it offers is readable before it is on; choosing waits until it is.
    expect(screen.getByRole("checkbox", { name: "notion-search" })).toBeDisabled();
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("switch", { name: "Use Notion in this agent" }),
    );

    expect(onChange).toHaveBeenCalledWith([personal("notion")]);
  });

  it("removes the server from the agent", async () => {
    const onChange = vi.fn();
    mount({ value: [personal("notion")], onChange });

    await settings("Pages.");
    await userEvent.click(screen.getByRole("button", { name: "Remove from agent" }));

    expect(onChange).toHaveBeenCalledWith([]);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("writes the approval chosen per group onto the binding", async () => {
    const onChange = vi.fn();
    mount({ value: [personal("notion")], onChange });

    await settings("Pages.");
    await userEvent.click(screen.getByRole("combobox", { name: "Approval for Changes things" }));
    // Nothing asks by default, so the choice worth recording is asking.
    await userEvent.click(await screen.findByRole("option", { name: "Ask first" }));

    expect(onChange).toHaveBeenCalledWith([{ ...personal("notion"), approval: "writes" }]);
  });

  it("keeps the approval when the binding moves to another kind of account", async () => {
    const onChange = vi.fn();
    const gh = connection({ id: "c1", name: "notion-org", catalog_key: "notion" });
    render(
      <McpServerPicker
        connections={[gh]}
        catalog={[NOTION]}
        value={[{ ...personal("notion"), approval: "all" }]}
        onChange={onChange}
        onTools={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

    await settings("Pages.");
    await userEvent.click(kind("organization"));

    expect(onChange).toHaveBeenCalledWith([{ ...bound("c1"), approval: "all" }]);
  });

  it("connects another of the reader's own accounts, and counts the ones it reaches", async () => {
    const onConnectOwn = vi.fn();
    mount({ value: [personal("notion")], onConnectOwn, own: 2 });

    await settings("Pages.");
    expect(screen.getByText(/You have 2 accounts connected/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect another account" }));

    expect(onConnectOwn).toHaveBeenCalledWith(NOTION);
  });
});

describe("the reader's own accounts in a server's settings", () => {
  const NOTION = entry({ key: "notion", name: "Notion", auth: "oauth", description: "Pages." });
  const WORK = connection({
    id: "p1",
    name: "notion",
    label: "Work",
    catalog_key: "notion",
    is_default: true,
  });
  const SIDE = connection({ id: "p2", name: "notion-2", catalog_key: "notion", authorized: false });
  const OFF = connection({ id: "p3", name: "notion-3", catalog_key: "notion", is_enabled: false });
  const mount = (handlers: {
    onDisconnectOwn?: (connection: McpConnectionRecord) => void;
    onSignInOwn?: (connection: McpConnectionRecord) => void;
  }) =>
    render(
      <McpServerPicker
        connections={[]}
        catalog={[NOTION]}
        value={[personal("notion")]}
        onChange={vi.fn()}
        onTools={vi.fn()}
        onConnect={vi.fn()}
        personalConnections={[WORK, SIDE, OFF] as never}
        {...handlers}
      />,
    );

  it("lists each by name, with the main one marked and the prefix its tools carry", async () => {
    mount({});

    await settings("Pages.");
    const row = within(screen.getByText("Work").closest("li")!);
    expect(row.getByText("Main")).toBeInTheDocument();
    expect(row.getByText("Its tools start with notion")).toBeInTheDocument();
    expect(
      within(screen.getByText("notion-2").closest("li")!).getByText("Needs authorization"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Rename or choose your main account/ }),
    ).toHaveAttribute("target", "_blank");
  });

  it("disconnects one only on the second click", async () => {
    const onDisconnectOwn = vi.fn();
    mount({ onDisconnectOwn });

    await settings("Pages.");
    await userEvent.click(screen.getByRole("button", { name: "Disconnect Work" }));
    expect(onDisconnectOwn).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect for good" }));

    expect(onDisconnectOwn).toHaveBeenCalledWith(WORK);
  });

  it("signs in again an account whose grant lapsed", async () => {
    const onSignInOwn = vi.fn();
    mount({ onSignInOwn });

    await settings("Pages.");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(onSignInOwn).toHaveBeenCalledWith(SIDE);
  });
});

describe("a further account in a server's settings", () => {
  const THREE_GH = [
    connection({ id: "c1", name: "gh-admin", catalog_key: "github" }),
    connection({ id: "c2", name: "gh-readonly", catalog_key: "github" }),
  ];

  it("moves a further account from each person's own to the organization's", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE_GH, value: [bound("c1"), personal("github")], onChange }));

    await settings();
    await userEvent.click(screen.getByRole("combobox", { name: /^Whose GitHub account/ }));
    await userEvent.click(
      await screen.findByRole("option", { name: "The organization's account" }),
    );

    expect(onChange).toHaveBeenCalledWith([bound("c1"), bound("c2")]);
  });

  it("opens a server's settings from the line at the foot of its card", async () => {
    render(picker({ connections: THREE_GH }));

    await userEvent.click(
      screen.getByRole("button", { name: "Settings for GitHub in this agent" }),
    );

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

describe("bindingKey", () => {
  it("tells the two kinds apart even when their ids coincide", () => {
    expect(bindingKey(bound("notion"))).not.toBe(bindingKey(personal("notion")));
  });

  it("names the platform's own server once, whatever its settings", () => {
    expect(bindingKey({ account: "platform", allowed_tools: null, approval: "writes" })).toBe(
      "platform",
    );
    expect(bindingKey({ account: "platform", allowed_tools: null, approval: "all" })).toBe(
      "platform",
    );
  });

  it("is the same for the same binding whatever its tools", () => {
    expect(bindingKey(personal("notion", ["search"]))).toBe(bindingKey(personal("notion")));
  });
});
