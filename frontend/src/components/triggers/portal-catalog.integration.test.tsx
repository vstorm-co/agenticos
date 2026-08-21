import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalCatalog } from "./portal-catalog";
import { apiClient } from "@/lib/api-client";
import { startGithubOrgOAuth, startMcpOAuth } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("@/lib/mcp-connections-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/mcp-connections-api")>(
    "@/lib/mcp-connections-api",
  );
  return { ...actual, startMcpOAuth: vi.fn(), startGithubOrgOAuth: vi.fn() };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The catalog as the server answers it: GitHub's connection state is derived
 * from the org connection exactly the way `AgentTriggerService.list_portals`
 * derives it, so these tests keep expressing states as connections. */
function portalsFor(
  org: OrgMcpConnectionRecord[],
  blockedBy: "oauth_app_secret" | "ambiguous_oauth_app_secret" | null = null,
) {
  const c = org.find((row) => row.catalog_key === "github") ?? null;
  const state =
    c === null
      ? null
      : c.auth_type === "oauth" && !c.oauth_authorized
        ? "needs_authorization"
        : !c.is_enabled
          ? "disabled"
          : c.last_status === "error"
            ? "error"
            : "connected";
  return {
    items: [
      {
        key: "github",
        name: "GitHub",
        description: "Run an agent when a repository event arrives.",
        category: "development",
        icon: "github",
        event_source: "github",
        delivery: "auto_webhook",
        webhook_admin_scopes: ["admin:repo_hook"],
        target_kind: "repo",
        connection_catalog_key: "github",
        connection_id: c?.id ?? null,
        connection_state: state,
        connection_covers_webhook_scopes: (c?.granted_scopes ?? []).includes("admin:repo_hook"),
        connect_blocked_by: blockedBy,
        presets: [
          {
            key: "issue_opened",
            label: "New issue opened",
            description: "…",
            target_required: true,
          },
        ],
      },
      {
        key: "email",
        name: "Email",
        description: "Run an agent when an email arrives.",
        category: "productivity",
        icon: "gmail",
        event_source: "email",
        delivery: "manual",
        webhook_admin_scopes: [],
        target_kind: null,
        connection_catalog_key: null,
        connection_id: null,
        connection_state: null,
        connection_covers_webhook_scopes: false,
        connect_blocked_by: null,
        presets: [
          {
            key: "any_email",
            label: "Any incoming email",
            description: "…",
            target_required: false,
          },
        ],
      },
      {
        // A non-GitHub auto-webhook portal: it still connects through the generic
        // discovery flow, which is what tells the GitHub branch apart from it.
        key: "tracker",
        name: "Tracker",
        description: "Run an agent when a ticket arrives.",
        category: "productivity",
        icon: "linear",
        event_source: "webhook",
        delivery: "auto_webhook",
        webhook_admin_scopes: [],
        target_kind: null,
        connection_catalog_key: null,
        connection_id: null,
        connection_state: null,
        connection_covers_webhook_scopes: false,
        connect_blocked_by: null,
        presets: [
          { key: "new_ticket", label: "New ticket", description: "…", target_required: false },
        ],
      },
    ],
    total: 3,
  };
}

const MCP_CATALOG = {
  items: [
    {
      key: "github",
      name: "GitHub",
      description: "Read issues.",
      category: "development",
      auth: "oauth",
      url: "https://api.githubcopilot.com/mcp/",
      docs_url: null,
      token_hint: null,
      icon: "github",
    },
  ],
  total: 1,
};

function orgConnection(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "o1",
    name: "github",
    url: "https://api.githubcopilot.com/mcp/",
    has_auth_token: false,
    allowed_tools: null,
    is_enabled: true,
    auth_type: "oauth",
    oauth_authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: "github",
    granted_scopes: ["repo", "admin:repo_hook"],
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function serve(
  org: OrgMcpConnectionRecord[],
  blockedBy: "oauth_app_secret" | "ambiguous_oauth_app_secret" | null = null,
) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/trigger-portals") return portalsFor(org, blockedBy);
    if (path === "/agents/mcp-catalog") return MCP_CATALOG;
    if (path === "/mcp-connections") return { items: org, total: org.length };
    if (path === "/me/mcp-connections") return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount({
  canRun = true,
  canManageConnections = true,
  org = [] as OrgMcpConnectionRecord[],
  blockedBy = null as "oauth_app_secret" | "ambiguous_oauth_app_secret" | null,
} = {}) {
  serve(org, blockedBy);
  render(<PortalCatalog canRun={canRun} canManageConnections={canManageConnections} />, {
    wrapper,
  });
  await screen.findByText("GitHub");
}

const githubRow = () => within(screen.getByRole("group", { name: "GitHub" }));
const emailRow = () => within(screen.getByRole("group", { name: "Email" }));
const trackerRow = () => within(screen.getByRole("group", { name: "Tracker" }));

describe("PortalCatalog", () => {
  beforeEach(() => vi.clearAllMocks());

  it("draws a card per portal with its own brand mark", async () => {
    await mount();
    expect(screen.getByRole("group", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Email" })).toBeInTheDocument();
    // Presets are shown on the card so the choice is visible before opening it.
    expect(githubRow().getByText("New issue opened")).toBeInTheDocument();
    // The category slug reads title-cased, not the lower-case "development".
    expect(githubRow().getByText("Development")).toBeInTheDocument();
  });

  it("says nothing matches rather than an empty grid when a search excludes every portal", async () => {
    await mount();

    await userEvent.type(
      screen.getByRole("textbox", { name: "Search portals…" }),
      "no-such-portal",
    );

    expect(await screen.findByText("No portals match")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "GitHub" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Email" })).toBeNull();
  });

  it("draws the API trigger as a card in the grid, not a button above it", async () => {
    // It is one of the ways to make an event trigger, so it sits beside the
    // others rather than as a ghost button in the filter row (#1071).
    await mount();

    const card = within(screen.getByRole("group", { name: "API trigger" }));

    expect(card.getByRole("button", { name: "Create trigger" })).toBeInTheDocument();
  });

  it("keeps the API trigger reachable when a search matches no portal", async () => {
    // The filter searches portals; the API card is not one, and a filter must not
    // take away the only way to trigger from a provider no portal covers.
    await mount();

    await userEvent.type(
      screen.getByRole("textbox", { name: "Search portals…" }),
      "no-such-portal",
    );

    expect(await screen.findByText("No portals match")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "API trigger" })).toBeInTheDocument();
  });

  it("hides the API trigger from a caller who may not run an agent", async () => {
    await mount({ canRun: false });

    expect(screen.queryByRole("group", { name: "API trigger" })).toBeNull();
  });

  it("does not offer Connect at all when it could only fail", async () => {
    // The button stayed beside the explanation and went on erroring, which is
    // worse than the toast it replaced: a control that says it will connect and
    // cannot (#1068).
    await mount({ org: [], blockedBy: "oauth_app_secret" });

    const card = within(screen.getByRole("group", { name: "GitHub" }));

    expect(card.queryByRole("button", { name: "Connect account" })).toBeNull();
    expect(card.getByRole("button", { name: /Add credentials/ })).toBeEnabled();
  });

  it("offers the vault's own form rather than sending you to another page", async () => {
    const user = userEvent.setup();
    await mount({ org: [], blockedBy: "oauth_app_secret" });

    await user.click(
      within(screen.getByRole("group", { name: "GitHub" })).getByRole("button", {
        name: /Add credentials/,
      }),
    );

    expect(await screen.findByRole("dialog", { name: /secret/i })).toBeInTheDocument();
  });

  it("cannot add a second one when two are already stored", async () => {
    // Ambiguity is fixed by removing one, which is the vault's job - so the add
    // control would make it worse.
    await mount({ org: [], blockedBy: "ambiguous_oauth_app_secret" });

    const card = within(screen.getByRole("group", { name: "GitHub" }));

    expect(card.getByRole("button", { name: /Add credentials/ })).toBeDisabled();
    expect(card.getByRole("link", { name: "Open the vault" })).toHaveAttribute("href", "/vault");
  });

  it("names the missing OAuth App on the card instead of after the click", async () => {
    // Connecting GitHub builds its consent URL from the organization's own OAuth
    // App credentials, so with none stored the press could only fail - and did,
    // as a red toast. The prerequisite and where to fix it are on the card (#1068).
    await mount({ org: [], blockedBy: "oauth_app_secret" });

    const card = within(screen.getByRole("group", { name: "GitHub" }));

    expect(card.getByText(/GitHub OAuth App credentials/)).toBeVisible();
    expect(card.getByRole("link", { name: "Open the vault" })).toHaveAttribute("href", "/vault");
    // And the toast that used to be the only way to learn this is not the path:
    // nothing was clicked to get here.
    expect(vi.mocked(startGithubOrgOAuth)).not.toHaveBeenCalled();
  });

  it("says which of the two credential problems it is", async () => {
    await mount({ org: [], blockedBy: "ambiguous_oauth_app_secret" });

    expect(
      within(screen.getByRole("group", { name: "GitHub" })).getByText(/cannot tell which one/),
    ).toBeVisible();
  });

  it("does not tell a caller who cannot fix it", async () => {
    // Storing the secret needs `mcp:manage`, the same permission the connect
    // control carries - so a Member reads a prerequisite they cannot act on.
    await mount({ org: [], blockedBy: "oauth_app_secret", canManageConnections: false });

    expect(
      within(screen.getByRole("group", { name: "GitHub" })).queryByText(/OAuth App/),
    ).toBeNull();
  });

  it("offers Connect account for an auto-webhook portal nobody has connected", async () => {
    await mount({ org: [] });
    expect(githubRow().getByRole("button", { name: "Connect account" })).toBeInTheDocument();
    expect(githubRow().queryByRole("button", { name: "Create trigger" })).toBeNull();
  });

  it("offers Create trigger once connected and the grant covers the webhook scope", async () => {
    await mount({ org: [orgConnection()] });
    expect(githubRow().getByRole("button", { name: "Create trigger" })).toBeInTheDocument();
    expect(githubRow().queryByRole("button", { name: "Connect account" })).toBeNull();
  });

  it("offers Re-authorize when connected but the grant lacks the webhook scope", async () => {
    // The distinct state: the account is connected, but its consent never included
    // admin:repo_hook, so it must be re-authorized before it can auto-register.
    await mount({ org: [orgConnection({ granted_scopes: ["repo"] })] });
    expect(githubRow().getByRole("button", { name: "Re-authorize" })).toBeInTheDocument();
    expect(githubRow().queryByRole("button", { name: "Create trigger" })).toBeNull();
  });

  it("offers Re-authorize when the connection has not finished consent", async () => {
    await mount({ org: [orgConnection({ oauth_authorized: false })] });
    expect(githubRow().getByRole("button", { name: "Re-authorize" })).toBeInTheDocument();
  });

  it("lets a manual portal create a trigger with no connected account", async () => {
    await mount({ org: [] });
    expect(emailRow().getByRole("button", { name: "Create trigger" })).toBeInTheDocument();
  });

  it("hides every action from a caller who may neither run agents nor manage connections", async () => {
    await mount({ canRun: false, canManageConnections: false, org: [] });
    expect(screen.queryByRole("button", { name: "Connect account" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Create trigger" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-authorize" })).toBeNull();
    // The raw-webhook escape hatch is also a create, so it is gated the same way.
    expect(screen.queryByRole("button", { name: "Advanced: API trigger" })).toBeNull();
  });

  it("connects GitHub through the org OAuth App endpoint, keyed by the portal", async () => {
    // GitHub cannot be MCP-discovered, so its Connect goes to the dedicated
    // endpoint with the portal key, not the generic discovery flow.
    vi.mocked(startGithubOrgOAuth).mockResolvedValue({
      authorization_url: "https://github/consent",
    });
    await mount({ org: [] });

    await userEvent.click(githubRow().getByRole("button", { name: "Connect account" }));

    await waitFor(() => expect(startGithubOrgOAuth).toHaveBeenCalledWith("github"));
    expect(startMcpOAuth).not.toHaveBeenCalled();
  });

  it("connects a non-GitHub portal through the generic discovery flow", async () => {
    vi.mocked(startMcpOAuth).mockResolvedValue({ authorization_url: "https://provider/consent" });
    await mount({ org: [] });

    await userEvent.click(trackerRow().getByRole("button", { name: "Connect account" }));

    await waitFor(() =>
      expect(startMcpOAuth).toHaveBeenCalledWith({ name: "Tracker", url: "" }, "organization"),
    );
    expect(startGithubOrgOAuth).not.toHaveBeenCalled();
  });

  it("says nothing yet rather than drawing an empty grid when the catalog is empty", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/trigger-portals") return { items: [], total: 0 };
      if (path === "/agents/mcp-catalog") return MCP_CATALOG;
      if (path === "/mcp-connections") return { items: [], total: 0 };
      if (path === "/me/mcp-connections") return { items: [], total: 0 };
      throw new Error(`unexpected GET ${path}`);
    });
    render(<PortalCatalog canRun canManageConnections />, { wrapper });

    expect(await screen.findByText("No portals yet")).toBeInTheDocument();
  });

  it("says a failed catalog out loud instead of as an empty grid", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/trigger-portals") throw new Error("boom");
      if (path === "/agents/mcp-catalog") return MCP_CATALOG;
      if (path === "/mcp-connections") return { items: [], total: 0 };
      if (path === "/me/mcp-connections") return { items: [], total: 0 };
      throw new Error(`unexpected GET ${path}`);
    });
    render(<PortalCatalog canRun canManageConnections />, { wrapper });

    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});
