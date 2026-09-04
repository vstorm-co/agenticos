import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectServicesCard } from "./connect-services-card";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { PersonalServiceGap } from "@/types";
import type { McpCatalogEntry } from "@/types/mcp";

const state = vi.hoisted(() => ({
  connections: [] as McpConnectionRecord[],
  servers: [] as McpCatalogEntry[],
}));

vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({ connections: state.connections }),
}));
vi.mock("@/hooks/use-mcp-servers", () => ({
  useMcpCatalog: () => ({ servers: state.servers, isLoading: false }),
}));
// The dialog is tested on its own; here it only has to be opened for the right
// entry, so it renders a marker naming the one it was given.
vi.mock("@/components/agents/connect-server-dialog", () => ({
  ConnectOwnServerDialog: ({
    entry,
    onClose,
  }: {
    entry: McpCatalogEntry | null;
    onClose: () => void;
  }) =>
    entry ? (
      <div role="dialog">
        connecting {entry.name}
        <button type="button" onClick={onClose}>
          close
        </button>
      </div>
    ) : null,
}));

const NOTION: McpCatalogEntry = {
  key: "notion",
  name: "Notion",
  description: "Pages and databases.",
  category: "productivity",
  auth: "oauth",
  url: "https://mcp.notion.com/mcp",
  docs_url: null,
  token_hint: null,
  icon: "notion",
};

function gap(overrides: Partial<PersonalServiceGap> = {}): PersonalServiceGap {
  return {
    catalog_key: "notion",
    name: "Notion",
    gap: "not_connected",
    url: "http://localhost:3000/mcp-servers?connect=notion",
    ...overrides,
  };
}

function own(overrides: Partial<McpConnectionRecord> = {}): McpConnectionRecord {
  return {
    id: "m1",
    name: "notion",
    url: "https://mcp.notion.com/mcp",
    has_auth_token: true,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "oauth",
    oauth_authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: "notion",
    is_default: false,
    label: null,
    last_tools: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("ConnectServicesCard", () => {
  beforeEach(() => {
    state.connections = [];
    state.servers = [NOTION];
  });

  it("names the service and offers to connect it in place", async () => {
    render(<ConnectServicesCard gaps={[gap()]} />);

    expect(screen.getByText("Notion")).toBeInTheDocument();
    expect(screen.getByText("You have not connected this yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("connecting Notion");
  });

  it("sends a person who already holds accounts to the servers page instead", () => {
    // `?connect=` would mint a third Notion; choosing between two is done there.
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    render(
      <ConnectServicesCard
        gaps={[gap({ gap: "undecided", url: "http://localhost:3000/mcp-servers" })]}
      />,
    );

    expect(
      screen.getByText("You hold several connections to it and none is marked as default."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    screen.getByRole("button", { name: "Open MCP servers" }).click();

    expect(opened).toHaveBeenCalledWith("http://localhost:3000/mcp-servers", "_blank", "noopener");
  });

  it("falls back to the link for a service the catalog no longer describes", () => {
    state.servers = [];
    render(<ConnectServicesCard gaps={[gap({ catalog_key: "gone", name: "gone" })]} />);

    expect(screen.getByRole("button", { name: "Open MCP servers" })).toBeInTheDocument();
  });

  it("turns a row into 'ask again' once the connection exists", () => {
    // The frame said "not connected" a moment ago; the connections list is what
    // says whether that still holds - written by the dialog, or refetched on focus
    // after the consent in the other tab.
    state.connections = [own()];
    render(<ConnectServicesCard gaps={[gap()]} />);

    expect(screen.getByText("Connected. Ask again.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("can be dismissed", async () => {
    render(<ConnectServicesCard gaps={[gap()]} />);

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("ConnectServicesCard's dialog", () => {
  it("closes when the person backs out of connecting", async () => {
    state.connections = [];
    state.servers = [NOTION];
    render(<ConnectServicesCard gaps={[gap()]} />);
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
