import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { McpServerPicker } from "./mcp-server-picker";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";
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
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("McpServerPicker", () => {
  it("names a connection after the catalog server it points at", () => {
    // The connection is called "gh" because the name is a tool prefix. Nobody
    // building an agent is looking for "gh".
    render(
      <McpServerPicker
        connections={[connection()]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.getByText("API token")).toBeInTheDocument();
  });

  it("falls back to the connection's own name for a server not in the catalog", () => {
    render(
      <McpServerPicker
        connections={[connection({ name: "internal-crm", url: "https://crm.internal/mcp" })]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "internal-crm" })).toBeInTheDocument();
  });

  it("reflects what the spec already references", () => {
    render(
      <McpServerPicker
        connections={[
          connection(),
          connection({ id: "c2", name: "linear", url: "https://mcp.linear.app/sse" }),
        ]}
        catalog={CATALOG}
        selectedIds={["c1"]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
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
    render(
      <McpServerPicker
        connections={[connection({ auth_type: "oauth", oauth_authorized: false })]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByText("Needs authorization")).toBeInTheDocument();
  });

  it("marks a server that answered with an error, louder than one merely idle", async () => {
    // Unreachable is the state that explains a run that half-worked; it must not
    // read like "not connected yet".
    render(
      <McpServerPicker
        connections={[connection({ last_status: "error" })]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

    expect(screen.getByText("Unreachable")).toBeInTheDocument();
  });

  it("reports the connection id that was clicked", async () => {
    const onToggle = vi.fn();
    render(
      <McpServerPicker
        connections={[connection()]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={onToggle}
        onConnect={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "GitHub" }));
    expect(onToggle).toHaveBeenCalledWith("c1");
  });

  it("is operable from the keyboard", async () => {
    const onToggle = vi.fn();
    render(
      <McpServerPicker
        connections={[connection()]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={onToggle}
        onConnect={vi.fn()}
      />,
    );
    screen.getByRole("checkbox", { name: "GitHub" }).focus();
    await userEvent.keyboard("{Enter}");
    expect(onToggle).toHaveBeenCalledWith("c1");
    await userEvent.keyboard(" ");
    expect(onToggle).toHaveBeenCalledTimes(2);
  });

  it("ignores interaction when the viewer cannot edit", async () => {
    const onToggle = vi.fn();
    render(
      <McpServerPicker
        connections={[connection()]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={onToggle}
        onConnect={vi.fn()}
        disabled
      />,
    );
    const target = screen.getByRole("checkbox", { name: "GitHub" });
    await userEvent.click(target);
    target.focus();
    await userEvent.keyboard("{Enter}");
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("shows spec references it cannot resolve instead of dropping them", () => {
    // An imported spec can name a server this organization does not have. If
    // the picker rendered nothing the next save would silently delete it, and
    // the publish refusal would name an id nothing on screen explains.
    render(
      <McpServerPicker
        connections={[connection()]}
        catalog={CATALOG}
        selectedIds={["c1", "00000000-0000-0000-0000-0000000000ff"]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );
    expect(screen.getByText(/1 server this organization does not offer/)).toBeInTheDocument();
    expect(screen.getByText("00000000-0000-0000-0000-0000000000ff")).toBeInTheDocument();
  });

  it("counts more than one unresolved reference in the plural", () => {
    render(
      <McpServerPicker
        connections={[connection()]}
        catalog={CATALOG}
        selectedIds={["gone-1", "gone-2"]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

    expect(screen.getByText(/2 servers this organization does not offer/)).toBeInTheDocument();
  });

  it("shows the whole catalog, not only what already has credentials", () => {
    // "What can I attach right now" was answerable; "what could this agent
    // reach at all" needed another page, and a catalog nobody sees is a catalog
    // nobody connects from.
    render(
      <McpServerPicker
        connections={[]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("offers to connect an unconnected server here rather than sending anyone away", async () => {
    // It used to be a link to `/mcp-servers`, which threw away an unsaved draft
    // and asked somebody to find their way back to the agent they were editing.
    const onConnect = vi.fn();
    render(
      <McpServerPicker
        connections={[]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={onConnect}
      />,
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("GitHub"));

    // The entry, so the caller's dialog can seed a form from it.
    expect(onConnect).toHaveBeenCalledWith(GITHUB);
  });

  it("an unconnected server is not a checkbox, because there is no id to bind", () => {
    // The spec stores connection ids; a catalog entry has none. A checkbox here
    // would be one that cannot write anything.
    const onToggle = vi.fn();
    render(
      <McpServerPicker
        connections={[]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={onToggle}
        onConnect={vi.fn()}
      />,
    );

    expect(screen.queryByRole("checkbox", { name: "GitHub" })).not.toBeInTheDocument();
  });

  it("hides the servers nobody connected when asked, which is most of the catalog", async () => {
    // Only a connected server can be bound to an agent. The rest are shown to
    // advertise, and sixty of them buries the two that can actually be picked.
    const linear = entry({ key: "linear", name: "Linear" });
    render(
      <McpServerPicker
        connections={[connection({ catalog_key: "github" })]}
        catalog={[...CATALOG, linear]}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
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
    render(
      <McpServerPicker
        connections={[]}
        catalog={[...CATALOG, linear]}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

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
   * entry, so four of the five vanished (#1341).
   */
  const THREE = [
    connection({ id: "c1", name: "gh-readonly", catalog_key: "github" }),
    connection({ id: "c2", name: "gh-issues", catalog_key: "github" }),
    connection({ id: "c3", name: "gh-admin", catalog_key: "github" }),
  ];

  it("shows one row per connection, not one per entry", () => {
    render(
      <McpServerPicker
        connections={THREE}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

    expect(screen.getAllByText("GitHub")).toHaveLength(3);
    // Told apart by the name the model sees as the tool prefix.
    for (const name of ["gh-readonly", "gh-issues", "gh-admin"]) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("binds the connection whose row was clicked", async () => {
    const onToggle = vi.fn();
    render(
      <McpServerPicker
        connections={THREE}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={onToggle}
        onConnect={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("gh-issues"));

    expect(onToggle).toHaveBeenCalledWith("c2");
  });

  it("lets an already-bound connection be unbound, whichever one it is", async () => {
    // The one that used to be dropped: bound in the spec, no row to click.
    const onToggle = vi.fn();
    render(
      <McpServerPicker
        connections={THREE}
        catalog={CATALOG}
        selectedIds={["c1"]}
        onToggle={onToggle}
        onConnect={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("gh-readonly"));

    expect(onToggle).toHaveBeenCalledWith("c1");
  });

  it("does not label the ordinary case, where one entry has one connection", () => {
    render(
      <McpServerPicker
        connections={[connection({ id: "c1", name: "gh", catalog_key: "github" })]}
        catalog={CATALOG}
        selectedIds={[]}
        onToggle={vi.fn()}
        onConnect={vi.fn()}
      />,
    );

    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.queryByText("gh")).not.toBeInTheDocument();
  });
});
