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

describe("who an organization server is for (#2072)", () => {
  it("marks one limited to groups, and only the organization's", () => {
    open([connection({ id: "c1", name: "ledger", visibility: "private" })]);

    expect(screen.getAllByText("Limited")).toHaveLength(1);
    // A person's own account is theirs whatever its column says: no badge, no action.
    expect(screen.getAllByRole("button", { name: "Who can use it" })).toHaveLength(1);
  });

  it("opens the sharing panel for the server", async () => {
    open([connection({ id: "c1", label: "Finance ledger" })]);

    await userEvent.click(screen.getByRole("button", { name: "Who can use it" }));

    expect(screen.getByRole("heading", { name: "Who can use Finance ledger" })).toBeInTheDocument();
    expect(screen.getByText("sharing mcp_connection c1")).toBeInTheDocument();
  });

  it("closes the panel again", async () => {
    open([connection({ id: "c1" })]);

    await userEvent.click(screen.getByRole("button", { name: "Who can use it" }));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByText("sharing mcp_connection c1")).not.toBeInTheDocument();
  });

  it("offers no change to somebody who cannot manage the organization's servers", () => {
    open([connection({ id: "c1", visibility: "private" })], false);

    expect(screen.queryByRole("button", { name: "Who can use it" })).not.toBeInTheDocument();
  });
});

describe("what an organization server is used for (#2072)", () => {
  it("names the agents binding it, and nothing on a person's own", () => {
    open([connection({ id: "c1", used_by: [{ id: "a1", name: "Writer" }] })]);

    expect(screen.getByText(/Writer/)).toBeInTheDocument();
  });

  it("opens and closes the server's call log", async () => {
    open([connection({ id: "c1" })]);

    await userEvent.click(screen.getByRole("button", { name: "What agents asked it" }));
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
