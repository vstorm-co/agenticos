import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalCatalog } from "./portal-catalog";
import { apiClient } from "@/lib/api-client";
import {
  startGithubOrgOAuth,
  startMcpOAuth,
  startPolledPortalOAuth,
} from "@/lib/mcp-connections-api";
import { toast } from "sonner";
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
  return {
    ...actual,
    startMcpOAuth: vi.fn(),
    startGithubOrgOAuth: vi.fn(),
    startPolledPortalOAuth: vi.fn(),
  };
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
type BlockedBy = "oauth_app_secret" | "ambiguous_oauth_app_secret" | "oauth_unavailable" | null;

/** A polled portal - Gmail - appended only for the tests that ask for one. */
function polledPortal(blockedBy: BlockedBy) {
  return {
    key: "google",
    name: "Gmail",
    description: "Run an agent when a message arrives in your mailbox.",
    category: "productivity",
    icon: "gmail",
    event_source: "gmail",
    delivery: "polling",
    webhook_admin_scopes: [],
    target_kind: null,
    connection_catalog_key: null,
    connection_id: null,
    connection_state: null,
    connection_covers_webhook_scopes: false,
    connect_blocked_by: blockedBy,
    oauth_app_kind: "google_oauth_app",
    presets: [
      { key: "any_message", label: "Any new message", description: "…", target_required: false },
    ],
  };
}

/**
 * Microsoft 365: polled, connected through the Entra app, and with no presets
 * yet - the account is all it offers so far.
 */
function microsoftPortal(overrides: Record<string, unknown> = {}) {
  return {
    key: "microsoft",
    name: "Microsoft 365",
    description: "Connect the organization's Microsoft 365 account.",
    category: "productivity",
    icon: "microsoft",
    event_source: null,
    delivery: "polling",
    webhook_admin_scopes: [],
    target_kind: null,
    connection_catalog_key: null,
    connection_id: null,
    connection_state: null,
    connection_covers_webhook_scopes: false,
    connect_blocked_by: null,
    oauth_app_kind: "entra_app",
    presets: [],
    ...overrides,
  };
}

function portalsFor(org: OrgMcpConnectionRecord[], blockedBy: BlockedBy = null) {
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
        oauth_app_kind: "github_oauth_app",
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
        oauth_app_kind: null,
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
        oauth_app_kind: null,
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

/** Enough of the vault's own catalog for its dialog to render inside this grid. */
const SECRET_KINDS = {
  items: [
    {
      kind: "api_key",
      name: "API key",
      json_schema: { type: "object", properties: { api_key: { type: "string" } } },
    },
    {
      kind: "github_oauth_app",
      name: "GitHub OAuth App",
      json_schema: {
        type: "object",
        properties: { client_id: { type: "string" }, client_secret: { type: "string" } },
      },
    },
    {
      kind: "google_oauth_app",
      name: "Google OAuth client",
      json_schema: {
        type: "object",
        properties: { client_id: { type: "string" }, client_secret: { type: "string" } },
      },
    },
    {
      kind: "entra_app",
      name: "Microsoft Entra app",
      json_schema: {
        type: "object",
        properties: {
          tenant_id: { type: "string" },
          client_id: { type: "string" },
          client_secret: { type: "string" },
        },
      },
    },
  ],
  total: 4,
};

const SECRET_PURPOSES = {
  items: [
    {
      id: "openai",
      label: "OpenAI",
      category: "model_provider",
      kind: "api_key",
      help_url: null,
      description: "Run models on OpenAI.",
      icon: "",
    },
    {
      id: "github_oauth_app",
      label: "GitHub OAuth App",
      category: "other",
      kind: "github_oauth_app",
      help_url: null,
      description: "A GitHub OAuth App's client id and secret.",
      icon: "github",
    },
    {
      id: "google_oauth_app",
      label: "Google OAuth client",
      category: "other",
      kind: "google_oauth_app",
      help_url: null,
      description: "A Google OAuth client's id and secret.",
      icon: "google",
    },
  ],
  total: 3,
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
    authorized: true,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: "github",
    is_default: false,
    label: null,
    last_tools: null,
    granted_scopes: ["repo", "admin:repo_hook"],
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function serve(
  org: OrgMcpConnectionRecord[],
  blockedBy: BlockedBy = null,
  polled: BlockedBy | undefined = undefined,
  extra: object[] = [],
) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/trigger-portals") {
      const catalog = portalsFor(org, blockedBy);
      const items = [
        ...catalog.items,
        ...(polled === undefined ? [] : [polledPortal(polled)]),
        ...extra,
      ];
      return { items, total: items.length };
    }
    if (path === "/mcp-connections/portals/microsoft/admin-consent") {
      return { url: "https://login.microsoftonline.com/contoso/v2.0/adminconsent?client_id=c" };
    }
    if (path === "/agents/mcp-catalog") return MCP_CATALOG;
    if (path === "/mcp-connections") return { items: org, total: org.length };
    if (path === "/me/mcp-connections") return { items: [], total: 0 };
    if (path === "/secrets") return { items: [], total: 0 };
    if (path === "/secrets/kinds") return SECRET_KINDS;
    if (path === "/secrets/purposes") return SECRET_PURPOSES;
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount({
  canRun = true,
  canManageConnections = true,
  org = [] as OrgMcpConnectionRecord[],
  blockedBy = null as BlockedBy,
  polled = undefined as BlockedBy | undefined,
  extra = [] as object[],
} = {}) {
  serve(org, blockedBy, polled, extra);
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
    // And one control, not two: a link to the vault beside it is a second door to
    // the same store, for a card whose answer is "there are none yet".
    expect(card.queryByRole("link", { name: "Open the vault" })).toBeNull();
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

  it("sends you to the vault to remove one when two are stored, and offers no add", async () => {
    // Ambiguity is fixed by removing one, which is the vault's job - so adding a
    // third is the one thing that would make it worse, and a disabled button
    // beside the link was two controls for one answer.
    await mount({ org: [], blockedBy: "ambiguous_oauth_app_secret" });

    const card = within(screen.getByRole("group", { name: "GitHub" }));

    expect(card.queryByRole("button", { name: /Add credentials/ })).toBeNull();
    expect(card.getByRole("link", { name: "Open the vault" })).toHaveAttribute("href", "/vault");
  });

  it("names the missing OAuth App on the card instead of after the click", async () => {
    // Connecting GitHub builds its consent URL from the organization's own OAuth
    // App credentials, so with none stored the press could only fail - and did,
    // as a red toast. The prerequisite and where to fix it are on the card (#1068).
    await mount({ org: [], blockedBy: "oauth_app_secret" });

    const card = within(screen.getByRole("group", { name: "GitHub" }));

    expect(card.getByText(/GitHub OAuth App credentials/)).toBeVisible();
    expect(card.getByRole("button", { name: /Add credentials/ })).toBeEnabled();
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

  it("says a polled portal's own prerequisite, not the GitHub one beside it", async () => {
    // `connect_blocked_by` has three values and the card chose its sentence with a
    // two-way ternary, so the third fell through to GitHub's: a Gmail card read
    // "Two org-visible GitHub OAuth App secrets are stored, so connecting cannot
    // tell which one you meant" - about a portal that has nothing to do with
    // OAuth Apps, and while none were stored.
    await mount({ blockedBy: "oauth_app_secret", polled: "oauth_unavailable" });

    const gmail = within(screen.getByRole("group", { name: "Gmail" }));

    expect(gmail.getByText(/names no credential to connect with/)).toBeVisible();
    expect(gmail.queryByText(/cannot tell which one/)).toBeNull();
    expect(gmail.queryByText(/GitHub OAuth App credentials/)).toBeNull();
  });

  it("offers no vault control for a prerequisite the vault cannot fix", async () => {
    // The portal declares no credential at all. A disabled Add credentials and a
    // link to a store holding nothing relevant are two controls that lie about
    // what would help.
    await mount({ polled: "oauth_unavailable" });

    const gmail = within(screen.getByRole("group", { name: "Gmail" }));

    expect(gmail.queryByRole("button", { name: /Add credentials/ })).toBeNull();
    expect(gmail.queryByRole("link", { name: "Open the vault" })).toBeNull();
  });

  it("opens the secret form on the service the card is asking for", async () => {
    // The shortcut passed the dialog one kind and left its own pickers alone, so
    // it opened on Model provider with OpenAI chosen - and `kindInfo` then found
    // nothing for `api_key` in a list holding only `github_oauth_app`, leaving a
    // form with no value fields and Store secret disabled for ever.
    const user = userEvent.setup();
    await mount({ org: [], blockedBy: "oauth_app_secret" });

    await user.click(
      within(screen.getByRole("group", { name: "GitHub" })).getByRole("button", {
        name: /Add credentials/,
      }),
    );

    const dialog = within(await screen.findByRole("dialog", { name: /secret/i }));
    expect(dialog.getByDisplayValue("GitHub OAuth App")).toBeInTheDocument();
  });

  it("asks for the credential the card's own portal spends", async () => {
    // Hardcoded, this opened Gmail's dialog on a GitHub OAuth App - which is not
    // merely the wrong default: with GitHub's kind chosen, the form asks for the
    // wrong two fields and stores a credential the mailbox flow will not find.
    const user = userEvent.setup();
    await mount({ polled: "oauth_app_secret" });

    await user.click(
      within(screen.getByRole("group", { name: "Gmail" })).getByRole("button", {
        name: /Add credentials/,
      }),
    );

    const dialog = within(await screen.findByRole("dialog", { name: /secret/i }));
    expect(dialog.getByDisplayValue("Google OAuth client")).toBeInTheDocument();
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

  it("names the credential the blocked portal spends, not GitHub's", async () => {
    // The sentence was GitHub's whatever the portal, so a Microsoft 365 card with
    // no Entra app stored asked for an OAuth App it would never read.
    await mount({ extra: [microsoftPortal({ connect_blocked_by: "oauth_app_secret" })] });

    const card = within(screen.getByRole("group", { name: "Microsoft 365" }));

    expect(await card.findByText(/organization's Microsoft Entra app credentials/)).toBeVisible();
    expect(card.queryByText(/GitHub OAuth App/)).toBeNull();
  });

  it("names a credential the vault does not list generically", async () => {
    await mount({
      extra: [
        microsoftPortal({ connect_blocked_by: "oauth_app_secret", oauth_app_kind: "retired" }),
      ],
    });

    const card = within(screen.getByRole("group", { name: "Microsoft 365" }));

    expect(await card.findByText(/organization's OAuth client credentials/)).toBeVisible();
  });

  it("says a connected portal with no presets is connected rather than offering a create", async () => {
    // Microsoft 365 connects an account and fires nothing yet, so Create trigger
    // would open a picker with nothing in it.
    await mount({
      extra: [microsoftPortal({ connection_id: "g1", connection_state: "connected" })],
    });

    const card = within(screen.getByRole("group", { name: "Microsoft 365" }));

    expect(card.getByText("Connected")).toBeVisible();
    expect(card.queryByRole("button", { name: "Create trigger" })).toBeNull();
  });

  it("comes back to this page after the consent rather than to the MCP servers one", async () => {
    vi.mocked(startPolledPortalOAuth).mockResolvedValue({
      authorization_url: "https://login.microsoftonline.com/consent",
    });
    window.history.replaceState({}, "", "/routines?tab=events");
    await mount({ extra: [microsoftPortal()] });

    await userEvent.click(
      within(screen.getByRole("group", { name: "Microsoft 365" })).getByRole("button", {
        name: "Connect account",
      }),
    );

    await waitFor(() => expect(startPolledPortalOAuth).toHaveBeenCalledWith("microsoft"));
    expect(document.cookie).toContain(
      `mcp_oauth_return=${encodeURIComponent("/routines?tab=events")}`,
    );
  });

  it("copies the link an administrator approves the app for the tenant at", async () => {
    // Offered before anybody connects: an administrator approving first is what
    // spares the first member Entra's "Need admin approval" screen.
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await mount({ extra: [microsoftPortal()] });

    await userEvent.click(
      within(screen.getByRole("group", { name: "Microsoft 365" })).getByRole("button", {
        name: "Copy admin-consent link",
      }),
    );

    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        "https://login.microsoftonline.com/contoso/v2.0/adminconsent?client_id=c",
      ),
    );
    expect(toast.success).toHaveBeenCalledWith(expect.stringMatching(/Admin-consent link copied/));
  });

  it("says so when the admin-consent link cannot be had", async () => {
    await mount({ extra: [microsoftPortal()] });
    vi.mocked(apiClient.get).mockRejectedValueOnce("offline");

    await userEvent.click(
      within(screen.getByRole("group", { name: "Microsoft 365" })).getByRole("button", {
        name: "Copy admin-consent link",
      }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Could not get the admin-consent link."),
    );
  });

  it("offers no admin-consent link on a card that cannot connect yet", async () => {
    // The link is built from the Entra app in the vault; with none stored there
    // is nothing for an administrator to approve.
    await mount({ extra: [microsoftPortal({ connect_blocked_by: "oauth_app_secret" })] });

    expect(
      within(screen.getByRole("group", { name: "Microsoft 365" })).queryByRole("button", {
        name: "Copy admin-consent link",
      }),
    ).toBeNull();
  });

  it("disconnects a polled portal's account after asking, and reads the catalog again", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount({
      extra: [microsoftPortal({ connection_id: "g1", connection_state: "connected" })],
    });
    const reads = vi
      .mocked(apiClient.get)
      .mock.calls.filter(([path]) => path === "/trigger-portals");
    const before = reads.length;

    await user.click(
      within(screen.getByRole("group", { name: "Microsoft 365" })).getByRole("button", {
        name: "Disconnect",
      }),
    );
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText(/stop reading it until an account is connected again/)).toBeVisible();
    await user.click(dialog.getByRole("button", { name: "Disconnect" }));

    await waitFor(() =>
      expect(apiClient.delete).toHaveBeenCalledWith("/mcp-connections/portals/microsoft"),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Microsoft 365 is disconnected."),
    );
    expect(
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/trigger-portals").length,
    ).toBeGreaterThan(before);
  });

  it("keeps the dialog open and says so when disconnecting fails", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.delete).mockRejectedValue("offline");
    await mount({
      extra: [microsoftPortal({ connection_id: "g1", connection_state: "connected" })],
    });

    await user.click(
      within(screen.getByRole("group", { name: "Microsoft 365" })).getByRole("button", {
        name: "Disconnect",
      }),
    );
    const dialog = within(await screen.findByRole("dialog"));
    await user.click(dialog.getByRole("button", { name: "Disconnect" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Could not disconnect the account."),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("cancels a disconnect without removing anything", async () => {
    const user = userEvent.setup();
    await mount({
      extra: [microsoftPortal({ connection_id: "g1", connection_state: "connected" })],
    });

    await user.click(
      within(screen.getByRole("group", { name: "Microsoft 365" })).getByRole("button", {
        name: "Disconnect",
      }),
    );
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("offers no Disconnect where nothing is connected, or to a caller who may not manage it", async () => {
    // A webhook portal's account also carries the hooks it registered, and is
    // removed where it was connected - so GitHub's card never offers it either.
    await mount({ org: [orgConnection()], extra: [microsoftPortal()] });

    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
  });

  it("hides the account controls from a caller without mcp:manage", async () => {
    await mount({
      canManageConnections: false,
      extra: [microsoftPortal({ connection_id: "g1", connection_state: "connected" })],
    });

    const card = within(screen.getByRole("group", { name: "Microsoft 365" }));

    expect(card.queryByRole("button", { name: "Disconnect" })).toBeNull();
    expect(card.queryByRole("button", { name: "Copy admin-consent link" })).toBeNull();
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
