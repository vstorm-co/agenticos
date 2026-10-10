import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ServerConnectionsDialog } from "./server-connections-dialog";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { McpServerRow } from "@/lib/mcp-servers";

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
