import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConnectAccountPrompt } from "./connect-account-prompt";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { ConnectionRequest } from "@/types";
import type { McpCatalogEntry } from "@/types/mcp";

const state = vi.hoisted(() => ({
  connections: [] as McpConnectionRecord[],
  loading: false,
  servers: [] as McpCatalogEntry[],
  opened: [] as { returnTo?: string; keepThisTab?: boolean }[],
}));

vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({ connections: state.connections, isLoading: state.loading }),
}));
vi.mock("@/hooks/use-mcp-servers", () => ({
  useMcpCatalog: () => ({ servers: state.servers, isLoading: false }),
}));
vi.mock("@/lib/locale-navigation", () => ({
  getPathname: ({ href, locale }: { href: string; locale: string }) => `/${locale}${href}`,
}));
// The dialog is tested on its own; here it only has to be opened for the right
// entry, with no `returnTo` and `keepThisTab` - the consent in a new tab, and
// never this one, which holds the paused run.
vi.mock("@/components/agents/connect-server-dialog", () => ({
  ConnectOwnServerDialog: ({
    entry,
    onClose,
    returnTo,
    keepThisTab,
  }: {
    entry: McpCatalogEntry | null;
    onClose: () => void;
    returnTo?: string;
    keepThisTab?: boolean;
  }) => {
    if (entry === null) return null;
    state.opened.push({ returnTo, keepThisTab });
    return (
      <div role="dialog">
        connecting {entry.name}
        <button type="button" onClick={onClose}>
          close
        </button>
      </div>
    );
  },
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

function request(overrides: Partial<ConnectionRequest> = {}): ConnectionRequest {
  return { catalog_key: "notion", name: "Notion", gap: "not_connected", ...overrides };
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
    authorized: true,
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

describe("ConnectAccountPrompt", () => {
  beforeEach(() => {
    state.connections = [];
    state.loading = false;
    state.servers = [NOTION];
    state.opened = [];
  });

  it("names the service and connects it without leaving the page", async () => {
    const onRespond = vi.fn();
    render(<ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />);

    expect(screen.getByText("The agent needs your Notion")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("connecting Notion");
    expect(state.opened.at(-1)).toEqual({ returnTo: undefined, keepThisTab: true });
    await userEvent.click(screen.getByRole("button", { name: "close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onRespond).not.toHaveBeenCalled();
  });

  it("carries on by itself once the connection shows up", () => {
    const onRespond = vi.fn();
    const { rerender } = render(
      <ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />,
    );
    expect(onRespond).not.toHaveBeenCalled();

    state.connections = [own()];
    rerender(<ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />);

    expect(onRespond).toHaveBeenCalledWith(true);
  });

  it("waits for the socket before carrying on", () => {
    const onRespond = vi.fn();
    const { rerender } = render(
      <ConnectAccountPrompt request={request()} disabled onRespond={onRespond} />,
    );

    state.connections = [own()];
    rerender(<ConnectAccountPrompt request={request()} disabled onRespond={onRespond} />);

    expect(onRespond).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  });

  it("does not take a list that already said connected as the fix", () => {
    // An expired token still reads as authorized; the server said it is not.
    state.connections = [own()];
    const onRespond = vi.fn();
    const { rerender } = render(
      <ConnectAccountPrompt
        request={request({ gap: "unauthorized" })}
        disabled={false}
        onRespond={onRespond}
      />,
    );
    rerender(
      <ConnectAccountPrompt
        request={request({ gap: "unauthorized" })}
        disabled={false}
        onRespond={onRespond}
      />,
    );

    expect(onRespond).not.toHaveBeenCalled();
  });

  it("reads what the list said once it has loaded, not while it loads", () => {
    state.loading = true;
    const onRespond = vi.fn();
    const { rerender } = render(
      <ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />,
    );

    state.loading = false;
    state.connections = [own()];
    rerender(<ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />);

    expect(onRespond).not.toHaveBeenCalled();
  });

  it("goes on without the service when skipped", async () => {
    const onRespond = vi.fn();
    render(<ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />);

    await userEvent.click(screen.getByRole("button", { name: "Skip" }));

    expect(onRespond).toHaveBeenCalledWith(false);
  });

  it("lets the person say they are done when the list cannot see it", async () => {
    const onRespond = vi.fn();
    render(<ConnectAccountPrompt request={request()} disabled={false} onRespond={onRespond} />);

    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(onRespond).toHaveBeenCalledWith(true);
  });

  it.each([
    ["undecided", "You hold several Notion connections. Mark one as default, then continue."],
    [
      "unauthorized",
      "Your Notion connection needs authorizing again. Authorize it, then continue.",
    ],
  ] as const)(
    "sends an account that needs fixing to the servers page in a new tab (%s)",
    (gap, said) => {
      render(
        <ConnectAccountPrompt request={request({ gap })} disabled={false} onRespond={vi.fn()} />,
      );

      expect(screen.getByText(said)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
      const link = screen.getByRole("link", { name: "Open MCP servers" });
      expect(link).toHaveAttribute("href", "/en/mcp-servers");
      expect(link).toHaveAttribute("target", "_blank");
    },
  );

  it("sends a service the catalog no longer describes to the servers page", () => {
    state.servers = [];

    render(<ConnectAccountPrompt request={request()} disabled={false} onRespond={vi.fn()} />);

    expect(screen.getByRole("link", { name: "Open MCP servers" })).toBeInTheDocument();
  });
});
