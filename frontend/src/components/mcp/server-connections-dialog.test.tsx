import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ServerConnectionsDialog } from "./server-connections-dialog";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { McpServerRow } from "@/lib/mcp-servers";

vi.mock("./mcp-call-log", () => ({
  McpCallLog: ({ connection, onClose }: { connection: { id: string }; onClose: () => void }) => (
    <button type="button" onClick={onClose}>{`calls of ${connection.id}`}</button>
  ),
}));
vi.mock("@/components/agents/add-to-agent", () => ({
  AddToAgent: ({ resource }: { resource: { kind: string; id: string } }) => (
    <p>{`add ${resource.kind} ${resource.id}`}</p>
  ),
}));
const org = vi.hoisted(() => ({ watches: true }));
vi.mock("@/hooks", () => ({
  useOrganizations: () => ({ activeOrg: { proactive_watches_enabled: org.watches } }),
}));
vi.mock("@/components/watches/watch-dialog", () => ({
  WatchDialog: ({
    connectionId,
    onOpenChange,
  }: {
    connectionId: string;
    onOpenChange: (open: boolean) => void;
  }) => (
    <button type="button" onClick={() => onOpenChange(false)}>{`watch ${connectionId}`}</button>
  ),
}));
vi.mock("@/components/sharing/sharing-panel", () => ({
  SharingPanel: ({ resourceType, resourceId }: { resourceType: string; resourceId: string }) => (
    <p>{`sharing ${resourceType} ${resourceId}`}</p>
  ),
}));

function connection(overrides: Partial<McpConnectionRecord>): McpConnectionRecord {
  return {
    id: "c1",
    name: "ledger",
    label: null,
    url: "https://ledger.example/mcp",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "bearer",
    oauth_authorized: false,
    authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    visibility: "org",
    catalog_key: null,
    is_default: false,
    created_at: "2026-10-10T00:00:00Z",
    updated_at: null,
    ...overrides,
  } as McpConnectionRecord;
}

function open(organizations: McpConnectionRecord[], canManageOrganization = true) {
  const row = {
    key: "ledger",
    name: "Ledger",
    organizations,
    personals: [connection({ id: "p1", name: "mine", visibility: "org" })],
  } as unknown as McpServerRow;
  render(
    <ServerConnectionsDialog
      row={row}
      canManageOrganization={canManageOrganization}
      busyId={null}
      onClose={vi.fn()}
      onConnect={vi.fn()}
      onEdit={vi.fn()}
      onTools={vi.fn()}
      onDisconnect={vi.fn()}
      onNominate={vi.fn()}
      onOAuth={vi.fn()}
    />,
  );
}

/** Open one account's menu - where everything but its next step lives. */
async function menuOf(name: string) {
  await userEvent.click(screen.getByRole("button", { name: `More for ${name}` }));
}

describe("watching one's own account (#2301)", () => {
  it("offers a watch beside Tools on a connected personal account", async () => {
    org.watches = true;
    open([connection({ id: "c1" })]);

    // One button: the organization's account offers none, the person's does.
    const watch = screen.getAllByRole("button", { name: "Watch" });
    expect(watch).toHaveLength(1);
    await userEvent.click(watch[0]!);
    // Beside the open dialog, which hides the rest of the page from the accessibility tree.
    fireEvent.click(screen.getByText("watch p1"));
    expect(screen.queryByText("watch p1")).toBeNull();
  });

  it("offers nothing where the organization has watches off", () => {
    org.watches = false;
    open([]);
    expect(screen.queryByRole("button", { name: "Watch" })).toBeNull();
    org.watches = true;
  });
});

describe("who an organization server is for (#2072)", () => {
  it("marks one limited to groups, and only the organization's", async () => {
    open([connection({ id: "c1", name: "ledger", visibility: "private" })]);

    expect(screen.getAllByText("Limited")).toHaveLength(1);
    await menuOf("ledger");
    expect(screen.getByRole("menuitem", { name: "Who can use it" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    // A person's own account is theirs whatever its column says: no badge, no action.
    await menuOf("mine");
    expect(screen.queryByRole("menuitem", { name: "Who can use it" })).toBeNull();
  });

  it("opens the sharing panel for the server", async () => {
    open([connection({ id: "c1", label: "Finance ledger" })]);

    await menuOf("Finance ledger");
    await userEvent.click(screen.getByRole("menuitem", { name: "Who can use it" }));

    expect(screen.getByRole("heading", { name: "Who can use Finance ledger" })).toBeInTheDocument();
    expect(screen.getByText("sharing mcp_connection c1")).toBeInTheDocument();
  });

  it("closes the panel again", async () => {
    open([connection({ id: "c1" })]);

    await menuOf("ledger");
    await userEvent.click(screen.getByRole("menuitem", { name: "Who can use it" }));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByText("sharing mcp_connection c1")).not.toBeInTheDocument();
  });

  it("offers no change to somebody who cannot manage the organization's servers", () => {
    open([connection({ id: "c1", visibility: "private" })], false);

    // Read-only: the organization's account has no menu at all.
    expect(screen.queryByRole("button", { name: "More for ledger" })).not.toBeInTheDocument();
  });
});

describe("what an organization server is used for (#2072)", () => {
  it("names the agents binding it, and nothing on a person's own", () => {
    open([connection({ id: "c1", used_by: [{ id: "a1", name: "Writer" }] })]);

    expect(screen.getByText(/Writer/)).toBeInTheDocument();
  });

  it("opens and closes the server's call log", async () => {
    open([connection({ id: "c1" })]);

    await menuOf("ledger");
    await userEvent.click(screen.getByRole("menuitem", { name: "What agents asked it" }));
    // Outside the open dialog, so hidden from the accessibility tree and from pointer events.
    fireEvent.click(screen.getByText("calls of c1"));

    expect(screen.queryByText("calls of c1")).not.toBeInTheDocument();
  });

  it("offers a usable organization account to an agent, and nothing else (#2075)", () => {
    open([
      connection({ id: "c1" }),
      connection({ id: "c2", name: "down", last_status: "error" }),
      connection({ id: "c3", name: "unsigned", authorized: false }),
      connection({ id: "c4", name: "off", is_enabled: false }),
    ]);

    expect(screen.getByText("add mcp c1")).toBeInTheDocument();
    expect(screen.getByText("add mcp c2")).toBeInTheDocument();
    expect(screen.queryByText("add mcp c3")).not.toBeInTheDocument();
    expect(screen.queryByText("add mcp c4")).not.toBeInTheDocument();
    // A person's own account is reached through bindings to each person's, never by id.
    expect(screen.queryByText("add mcp p1")).not.toBeInTheDocument();
  });
});

describe("one action in sight, the rest in the account's menu", () => {
  it("leads with Tools for a working account and keeps the rest behind More", async () => {
    open([connection({ id: "c1" })]);

    expect(screen.getAllByRole("button", { name: "Tools" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
    await menuOf("ledger");
    expect(screen.getByRole("menuitem", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Disconnect" })).toBeInTheDocument();
  });

  it("leads with Authorize for one that needs it, and moves Tools into the menu", async () => {
    open([
      connection({ id: "c1", auth_type: "oauth", oauth_authorized: false, authorized: false }),
    ]);

    expect(screen.getByRole("button", { name: "Authorize" })).toBeInTheDocument();
    await menuOf("ledger");
    expect(screen.getByRole("menuitem", { name: "Tools" })).toBeInTheDocument();
  });
});
