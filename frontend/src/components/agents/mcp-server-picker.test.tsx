import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { McpServerPicker } from "./mcp-server-picker";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
import type { McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";

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
    auth_type: "bearer",
    oauth_authorized: false,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
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

/** A bound server, with the substitution off - what ticking a row writes. */
function bound(
  connectionId: string,
  personal = false,
  tools: string[] | null = null,
): McpServerRef {
  return {
    connection_id: connectionId,
    use_personal_when_available: personal,
    allowed_tools: tools,
  };
}

function picker(props: {
  connections?: OrgMcpConnectionRecord[];
  catalog?: McpCatalogEntry[];
  value?: McpServerRef[];
  onChange?: (next: McpServerRef[]) => void;
  onTools?: (connection: OrgMcpConnectionRecord, ref: McpServerRef) => void;
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

describe("McpServerPicker", () => {
  it("names a connection after the catalog server it points at", () => {
    // The connection is called "gh" because the name is a tool prefix. Nobody
    // building an agent is looking for "gh".
    render(picker({ connections: [connection()] }));

    expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.getByText("API token")).toBeInTheDocument();
  });

  it("falls back to the connection's own name for a server not in the catalog", () => {
    render(
      picker({
        connections: [connection({ name: "internal-crm", url: "https://crm.internal/mcp" })],
      }),
    );

    expect(screen.getByRole("checkbox", { name: "internal-crm" })).toBeInTheDocument();
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

    expect(screen.getByRole("checkbox", { name: "GitHub" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("checkbox", { name: "linear" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("warns that a server cannot be reached before it is attached", () => {
    // Attaching a connection that has never been authorized is allowed - it may
    // be authorized later - but it should not look ready.
    render(picker({ connections: [connection({ auth_type: "oauth", oauth_authorized: false })] }));

    expect(screen.getByText("Needs authorization")).toBeInTheDocument();
  });

  it("marks a server that answered with an error, louder than one merely idle", () => {
    // Unreachable is the state that explains a run that half-worked; it must not
    // read like "not connected yet".
    render(picker({ connections: [connection({ last_status: "error" })] }));

    expect(screen.getByText("Unreachable")).toBeInTheDocument();
  });

  it("binds the connection whose card was clicked", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("drops a binding rather than writing it twice", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], value: [bound("c1")], onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("is operable from the keyboard", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], onChange }));

    screen.getByRole("checkbox", { name: "GitHub" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith([bound("c1")]);

    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("ignores interaction when the viewer cannot edit", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [connection()], onChange, disabled: true }));

    const target = screen.getByRole("checkbox", { name: "GitHub" });
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
    await userEvent.click(screen.getByText("GitHub"));

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
    // Only a connected server can be bound to an agent. The rest are shown to
    // advertise, and sixty of them buries the two that can actually be picked.
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
    render(picker({ connections: THREE }));

    expect(screen.getAllByText("GitHub")).toHaveLength(1);
    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    for (const name of ["gh-readonly", "gh-issues", "gh-admin"]) {
      expect(await screen.findByRole("option", { name })).toBeVisible();
    }
  });

  it("shows the bound account rather than the first, so the row says which is in use", () => {
    render(picker({ connections: THREE, value: [bound("c3")] }));

    expect(screen.getByRole("combobox", { name: /which github account/i })).toHaveTextContent(
      "gh-admin",
    );
    expect(screen.getByRole("checkbox", { name: "GitHub" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("replaces the bound account rather than binding a second one", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE, value: [bound("c1")], onChange }));

    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    await userEvent.click(await screen.findByRole("option", { name: "gh-issues" }));

    expect(onChange).toHaveBeenCalledWith([bound("c2")]);
  });

  it("carries the substitution across a change of account", async () => {
    // It is a property of the binding, not of the credential behind it, and
    // silently clearing it would leave an agent answering as the wrong party.
    const onChange = vi.fn();
    render(picker({ connections: THREE, value: [bound("c1", true)], onChange }));

    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    await userEvent.click(await screen.findByRole("option", { name: "gh-admin" }));

    expect(onChange).toHaveBeenCalledWith([bound("c3", true)]);
  });

  it("binds the account the select is showing", async () => {
    const onChange = vi.fn();
    render(picker({ connections: THREE, onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1")]);
  });

  it("offers no choice where there is none to make", () => {
    render(picker({ connections: [connection({ id: "c1", name: "gh", catalog_key: "github" })] }));

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("cannot be re-pointed by a viewer who cannot edit", () => {
    render(picker({ connections: THREE, value: [bound("c1")], disabled: true }));

    expect(screen.getByRole("combobox", { name: /which github account/i })).toBeDisabled();
  });
});

describe("speaking as whoever is running the agent", () => {
  const NOTION = connection({ id: "c1", name: "gh", catalog_key: "github" });

  it("is not offered until the server is bound", () => {
    // There would be no account to substitute, and a switch that writes nothing
    // is a promise the run will not keep.
    render(picker({ connections: [NOTION] }));

    expect(screen.queryByRole("checkbox", { name: /speak as/i })).not.toBeInTheDocument();
  });

  it("is off when a binding is made, because the organization's account is the reviewable answer", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [NOTION], onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));

    expect(onChange).toHaveBeenCalledWith([bound("c1", false)]);
  });

  it("writes the flag onto the binding it belongs to", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [NOTION], value: [bound("c1")], onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: /speak as/i }));

    expect(onChange).toHaveBeenCalledWith([bound("c1", true)]);
  });

  it("leaves the other bindings alone", async () => {
    const other = connection({ id: "c9", name: "linear", url: "https://mcp.linear.app/sse" });
    const onChange = vi.fn();
    render(
      picker({
        connections: [NOTION, other],
        value: [bound("c9", true), bound("c1")],
        onChange,
      }),
    );

    await userEvent.click(screen.getByRole("checkbox", { name: /speak as/i }));

    expect(onChange).toHaveBeenCalledWith([bound("c9", true), bound("c1", true)]);
  });

  it("turns back off", async () => {
    const onChange = vi.fn();
    render(picker({ connections: [NOTION], value: [bound("c1", true)], onChange }));

    await userEvent.click(screen.getByRole("checkbox", { name: /speak as/i }));

    expect(onChange).toHaveBeenCalledWith([bound("c1", false)]);
  });

  it("is not offered for a connection with no catalog key", () => {
    // Publish refuses one, for the reason there is nothing to match a member's
    // own connection against. Read off the connection rather than off the card:
    // `entryForConnection` also matches on URL, so this row renders under the
    // GitHub entry and still has no key to join anybody's own connection to.
    render(picker({ connections: [connection({ id: "c1" })], value: [bound("c1")] }));

    expect(screen.queryByRole("checkbox", { name: /speak as/i })).not.toBeInTheDocument();
  });
});

describe("which of a server's tools this agent may call", () => {
  /**
   * `allowed_tools` used to live only on the connection, so two agents bound to
   * one server got the same tools and the picker said so in its own docstring.
   * It is on the binding now, and the two intersect at run time - the
   * connection's list is an administrator's ceiling (#1341).
   */
  const NOTION = connection({ id: "c1", name: "gh", catalog_key: "github" });

  it("is not offered until the server is bound", () => {
    render(picker({ connections: [NOTION] }));

    expect(screen.queryByRole("button", { name: /tool/i })).not.toBeInTheDocument();
  });

  it("says every tool while the binding narrows nothing", () => {
    render(picker({ connections: [NOTION], value: [bound("c1")] }));

    expect(screen.getByRole("button", { name: "Every tool it offers" })).toBeVisible();
  });

  it("counts what the binding narrowed to", () => {
    render(picker({ connections: [NOTION], value: [bound("c1", false, ["search", "fetch"])] }));

    expect(screen.getByRole("button", { name: "2 tools" })).toBeVisible();
  });

  it("hands the caller the connection and the binding it belongs to", async () => {
    const onTools = vi.fn();
    render(picker({ connections: [NOTION], value: [bound("c1", false, ["search"])], onTools }));

    await userEvent.click(screen.getByRole("button", { name: "1 tool" }));

    expect(onTools).toHaveBeenCalledWith(NOTION, bound("c1", false, ["search"]));
  });

  it("carries the choice across a change of account", async () => {
    // The tools are chosen for the agent; which account it speaks through is a
    // different question, and two accounts on one server expose the same tools.
    const onChange = vi.fn();
    const two = [
      connection({ id: "c1", name: "gh-work", catalog_key: "github" }),
      connection({ id: "c2", name: "gh-side", catalog_key: "github" }),
    ];
    render(picker({ connections: two, value: [bound("c1", true, ["search"])], onChange }));

    await userEvent.click(screen.getByRole("combobox", { name: /which github account/i }));
    await userEvent.click(await screen.findByRole("option", { name: "gh-side" }));

    expect(onChange).toHaveBeenCalledWith([bound("c2", true, ["search"])]);
  });

  it("cannot be opened by a viewer who cannot edit", () => {
    render(picker({ connections: [NOTION], value: [bound("c1")], disabled: true }));

    expect(screen.getByRole("button", { name: "Every tool it offers" })).toBeDisabled();
  });
});
