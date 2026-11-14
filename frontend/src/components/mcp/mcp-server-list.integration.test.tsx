import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { McpServerList } from "./mcp-server-list";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { McpCatalog, McpCatalogEntry } from "@/types/mcp";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { OrgMcpConnectionRecord } from "@/lib/org-mcp-connections-api";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const managedConnect = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-managed-app-connect", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/use-managed-app-connect")>()),
  useManagedAppConnect: () => managedConnect,
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CATALOG: McpCatalog = {
  items: [
    {
      key: "github",
      name: "GitHub",
      description: "Read issues and pull requests.",
      category: "development",
      auth: "token",
      url: "https://api.githubcopilot.com/mcp/",
      docs_url: null,
      token_hint: null,
      icon: "github",
    },
    {
      key: "linear",
      name: "Linear",
      description: "Search and update issues.",
      category: "project-management",
      auth: "oauth",
      url: "https://mcp.linear.app/sse",
      docs_url: null,
      token_hint: null,
      icon: "linear",
    },
  ],
  total: 2,
};

function connection(overrides: Partial<OrgMcpConnectionRecord> = {}): OrgMcpConnectionRecord {
  return {
    id: "o1",
    name: "github",
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
    catalog_key: "github",
    is_default: false,
    trust_read_only_hints: false,
    label: null,
    last_tools: null,
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** What the mirrored registry answers for the next search, set per test. */
let registryResults: McpCatalogEntry[] = [];
let catalogEntries = CATALOG.items;

/** Every `/agents/mcp-servers` path the component asked for. */
function listCalls(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.map(([path]) => path as string)
    .filter((path) => path.startsWith("/agents/mcp-servers"));
}

/** One registry entry, which differs from a catalog one by `reviewed`. */
function registryEntry(overrides: Partial<McpCatalogEntry> = {}): McpCatalogEntry {
  return {
    key: "com.example/thing",
    name: "Some Thing",
    description: "The publisher's own words.",
    category: "other",
    auth: "token",
    url: "https://mcp.example.test/mcp",
    docs_url: null,
    token_hint: null,
    icon: null,
    reviewed: false,
    ...overrides,
  };
}

/** Route each GET to the list it is asking for, so the two owners stay distinct. */
function serve(org: OrgMcpConnectionRecord[], own: McpConnectionRecord[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    // The unpaged curated catalog, which the category filter and the connection
    // dialogs read - a page cannot answer "which entry is this connection".
    if (path === "/agents/mcp-catalog")
      return { items: catalogEntries, total: catalogEntries.length };
    // The paged list, which is the grid. The server joins the curated rows and
    // the registry mirror; here the mock plays both, in that order.
    if (path.startsWith("/agents/mcp-servers")) {
      // Filters and pages the way the endpoint does. A mock that answered every
      // query with everything would make "the grid narrows to what was searched
      // for" a test of the mock.
      const params = new URLSearchParams(path.split("?")[1] ?? "");
      const needle = (params.get("q") ?? "").toLowerCase();
      const auth = params.get("auth") ?? "";
      const category = params.get("category") ?? "";
      const state = params.get("state") ?? "all";
      const skip = Number(params.get("skip") ?? 0);
      const limit = Number(params.get("limit") ?? 50);
      const normalize = (url: string) => {
        const parsed = new URL(url.trim());
        return `${parsed.origin}${parsed.pathname.replace(/\/+$/, "")}${parsed.search}${parsed.hash}`;
      };
      const accounts = [...org, ...own];
      const claimed = new Set<string>();
      const all: McpCatalogEntry[] = [...catalogEntries, ...registryResults].map((entry) => {
        const ids = accounts
          .filter(
            (account) =>
              account.catalog_key === entry.key ||
              (entry.url !== null && normalize(account.url) === normalize(entry.url)) ||
              account.name === entry.key,
          )
          .map((account) => account.id);
        ids.forEach((id) => claimed.add(id));
        return { ...entry, connection_ids: ids };
      });
      const customs = new Map<string, McpCatalogEntry>();
      for (const account of accounts.filter((each) => !claimed.has(each.id))) {
        const url = normalize(account.url);
        const existing = customs.get(url);
        if (existing) {
          existing.connection_ids!.push(account.id);
        } else {
          customs.set(url, {
            key: `custom:${url}`,
            name: account.name,
            description: "",
            category: "custom",
            auth:
              account.auth_type === "oauth" ? "oauth" : account.has_auth_token ? "token" : "none",
            url: account.url,
            docs_url: null,
            token_hint: null,
            icon: null,
            custom: true,
            connection_ids: [account.id],
          });
        }
      }
      all.push(...customs.values());
      const matched = all.filter((entry) => {
        const connected = entry.connection_ids!.length > 0;
        const hidden =
          entry.reviewed === false &&
          entry.check !== null &&
          entry.check !== undefined &&
          ["unreachable", "broken", "refused", "duplicate"].includes(entry.check.outcome);
        return (
          (state === "connected" || !hidden) &&
          (!needle ||
            [entry.key, entry.name, entry.description, entry.url ?? ""].some((value) =>
              value.toLowerCase().includes(needle),
            )) &&
          (!auth || entry.auth === auth) &&
          (!category || entry.category === category) &&
          (state === "all" || (state === "connected" ? connected : !connected))
        );
      });
      return {
        items: matched.slice(skip, skip + limit),
        total: matched.length,
        registry_total: registryResults.length,
      };
    }
    if (path === "/mcp-connections") return { items: org, total: org.length };
    if (path === "/me/mcp-connections") return { items: own, total: own.length };
    throw new Error(`unexpected GET ${path}`);
  });
}

/** Open the connections modal for GitHub, where every account is listed. */
async function openConnections() {
  await userEvent.click(
    within(githubRow()).getByRole("button", { name: /^Manage \d+ connections? on/ }),
  );
  return within(await screen.findByRole("dialog"));
}

/** The GitHub row, which is where every assertion below happens. */
function githubRow() {
  return screen.getByRole("group", { name: "GitHub" });
}

async function mount({
  canManageOrganization = true,
  org = [] as OrgMcpConnectionRecord[],
  own = [] as McpConnectionRecord[],
} = {}) {
  serve(org, own);
  render(<McpServerList canManageOrganization={canManageOrganization} />, { wrapper });
  await screen.findByText("GitHub");
}

// Opening a server writes `?server=` into jsdom's one URL, which every test
// shares; the next would start with that server's accounts open over the page.
beforeEach(() => {
  window.history.replaceState({}, "", "/mcp-servers");
  catalogEntries = CATALOG.items;
  registryResults = [];
});

describe("McpServerList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    registryResults = [];
  });

  it.each(["connect", "server"])(
    "routes a managed app's %s link to native setup without generic OAuth",
    async (parameter) => {
      catalogEntries = [
        ...CATALOG.items,
        {
          ...CATALOG.items[1]!,
          key: "composio-gmail",
          name: "Gmail",
          auth: "composio",
          url: null,
        },
      ];
      window.history.replaceState({}, "", `/connectors?${parameter}=composio-gmail`);
      await mount();
      await waitFor(() =>
        expect(managedConnect).toHaveBeenCalledWith("composio-gmail", { sameTab: true }),
      );
      expect(apiClient.post).not.toHaveBeenCalled();
      expect(screen.queryByRole("dialog")).toBeNull();
    },
  );

  it("keeps the card to two controls and counts what is behind them", async () => {
    // The card used to grow a chip per connection, so a server with three
    // accounts stood taller than its neighbours and the grid went ragged.
    await mount({ org: [connection()], own: [] });

    const row = within(githubRow());
    expect(row.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    expect(row.getByRole("button", { name: "Configure GitHub before connecting" })).toBeVisible();
    // Whose accounts it holds, as the foot's one line; its name says what it opens.
    expect(row.getByRole("button", { name: "Manage 1 connection on GitHub" })).toHaveTextContent(
      "The organization's account",
    );
  });

  it("separates the two owners in the modal, because that is the difference", async () => {
    // One server, two credentials, and a heading on each saying whose it is -
    // which decides where it can be used at all.
    await mount({ org: [connection({ name: "gh-org" })], own: [connection({ name: "gh-mine" })] });

    const dialog = await openConnections();

    expect(dialog.getByRole("heading", { name: "The organization's" })).toBeInTheDocument();
    expect(dialog.getByRole("heading", { name: "Yours" })).toBeInTheDocument();
    expect(dialog.getByText("gh-org")).toBeInTheDocument();
    expect(dialog.getByText("gh-mine")).toBeInTheDocument();
  });

  it("records provenance when a catalog server is connected for the organization", async () => {
    // Without catalog_key the join falls back to guessing from the URL, which
    // stops working the moment somebody points the connection at a proxy.
    await mount();
    vi.mocked(apiClient.post).mockResolvedValue(connection());

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    // Your own account is the default; the shared one is chosen on purpose.
    expect(screen.getByRole("radio", { name: /^My own account/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.click(screen.getByRole("radio", { name: /^One shared account/ }));
    await userEvent.type(screen.getByLabelText("Access token"), "ghp-secret-9876");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections", {
        name: "github",
        url: "https://api.githubcopilot.com/mcp/",
        auth_token: "ghp-secret-9876",
        catalog_key: "github",
        visibility: "org",
        group_ids: [],
        user_ids: [],
      }),
    );
  });

  it("offers OAuth for a personal connection, which is how a custom server behind a consent screen gets added", async () => {
    // The gap this closes: the dialog offered a token field and nothing else, so
    // a server behind OAuth could not be connected at all - even though the
    // backend's `oauth/start` takes "catalog **or custom**" and discovers the
    // endpoints from the server's own metadata.
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: /^My own account/ }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));

    expect(screen.getByRole("radio", { name: "OAuth" })).toBeInTheDocument();
  });

  it("offers OAuth for the organization too, because a shared service account is the common case", async () => {
    // An organization with one admin account that everybody's agents then use
    // is a real arrangement, and withholding the choice did not make it safer -
    // it made it impossible. The cost (the grant is the consenting person's at
    // the provider) is stated where the choice is made.
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: /^One shared account/ }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));

    expect(screen.getByRole("radio", { name: "OAuth" })).toBeInTheDocument();
  });

  it("shows one Connect and no chips when nobody has connected it", async () => {
    // The common row in a catalog this size. Anything more is noise repeated
    // fifty-nine times.
    await mount();

    const row = within(githubRow());
    expect(row.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    expect(row.queryByTitle(/^(Organization|You):/)).toBeNull();
  });

  it("holds an OAuth draft during start and preserves it after refusal", async () => {
    await mount();
    await userEvent.click(within(githubRow()).getByRole("button", { name: "Connect" }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    await userEvent.clear(screen.getByLabelText("Tool prefix"));
    await userEvent.type(screen.getByLabelText("Tool prefix"), "support-workspace");
    let rejectWrite: (error: Error) => void = () => {
      throw new Error("OAuth start not called");
    };
    vi.mocked(apiClient.post).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectWrite = reject;
        }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));
    expect(screen.getByLabelText("Tool prefix")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeVisible();
    await act(async () => rejectWrite(new Error("Controlled sign-in refusal")));
    await waitFor(() => expect(screen.getByLabelText("Tool prefix")).toBeEnabled());
    expect(screen.getByLabelText("Tool prefix")).toHaveValue("support-workspace");
    expect(screen.getByRole("button", { name: "Connect & check" })).toBeEnabled();
  });

  it("writes no connection row when OAuth is chosen - the callback does that", async () => {
    // Submitting the form would make an unauthorized bearer connection that then
    // has to be repaired. The grant comes back from the provider first.
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: /^My own account/ }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    expect(apiClient.post).not.toHaveBeenCalledWith("/me/mcp-connections", expect.anything());
  });

  it("reauthorizes the selected account at its saved URL rather than the card URL", async () => {
    const saved = connection({
      name: "github-finance",
      url: "https://gateway.example/Finance/mcp?tenant=Finance",
      auth_type: "oauth",
      authorized: false,
    });
    await mount({ own: [saved] });
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });

    const dialog = await openConnections();
    await userEvent.click(dialog.getByRole("button", { name: "Authorize" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/me/mcp-connections/oauth/start",
        expect.objectContaining({ name: saved.name, url: saved.url }),
      ),
    );
  });

  it("connects a Google server straight to consent, with no client fields", async () => {
    // The organization's Google app is read on the server: the member never types
    // a client ID or secret, and the start carries none.
    catalogEntries = [
      ...CATALOG.items,
      {
        ...CATALOG.items[1]!,
        key: "google-calendar",
        name: "Google Calendar",
        url: "https://calendarmcp.googleapis.com/mcp/v1",
        docs_url:
          "https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
      },
    ];
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });
    await mount();
    await userEvent.click(
      within(screen.getByRole("group", { name: "Google Calendar" })).getByRole("button", {
        name: "Connect",
      }),
    );
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/me/mcp-connections/oauth/start",
        expect.objectContaining({ url: "https://calendarmcp.googleapis.com/mcp/v1" }),
      ),
    );
    expect(vi.mocked(apiClient.post).mock.calls[0]?.[1]).not.toHaveProperty("client_id");
    expect(screen.queryByLabelText("Client ID")).toBeNull();
  });

  it("asks an admin for the organization's Google app when it is missing", async () => {
    catalogEntries = [
      ...CATALOG.items,
      {
        ...CATALOG.items[1]!,
        key: "google-calendar",
        name: "Google Calendar",
        url: "https://calendarmcp.googleapis.com/mcp/v1",
        docs_url:
          "https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
      },
    ];
    vi.mocked(apiClient.post).mockRejectedValue(
      Object.assign(new ApiError(404, "No Google app"), {
        details: { kind: "google_oauth_app" },
      }),
    );
    await mount();
    await userEvent.click(
      within(screen.getByRole("group", { name: "Google Calendar" })).getByRole("button", {
        name: "Connect",
      }),
    );
    expect(await screen.findByLabelText("Client ID")).toBeVisible();
    expect(screen.getByLabelText("Client secret")).toBeVisible();
  });

  it("tells a member to ask an admin when the organization has no Google app", async () => {
    catalogEntries = [
      ...CATALOG.items,
      {
        ...CATALOG.items[1]!,
        key: "google-calendar",
        name: "Google Calendar",
        url: "https://calendarmcp.googleapis.com/mcp/v1",
        docs_url:
          "https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
      },
    ];
    vi.mocked(apiClient.post).mockRejectedValue(
      Object.assign(new ApiError(404, "No Google app"), {
        details: { kind: "google_oauth_app" },
      }),
    );
    await mount({ canManageOrganization: false });
    await userEvent.click(
      within(screen.getByRole("group", { name: "Google Calendar" })).getByRole("button", {
        name: "Connect",
      }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Ask an admin to set up Google for this organization.",
      ),
    );
    expect(screen.queryByLabelText("Client ID")).toBeNull();
  });

  it("saves the org's Google client as the organization's app when an admin enters it", async () => {
    // The admin's client is the organization's, not theirs: it goes to the org
    // vault as the org's Google app, and the consent start carries no client at
    // all, so the connection is the admin's personal one reading that app.
    catalogEntries = [
      ...CATALOG.items,
      {
        ...CATALOG.items[1]!,
        key: "google-calendar",
        name: "Google Calendar",
        url: "https://calendarmcp.googleapis.com/mcp/v1",
        docs_url:
          "https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
      },
    ];
    let startCalls = 0;
    vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
      if (path === "/secrets") return {};
      startCalls += 1;
      if (startCalls === 1) {
        throw Object.assign(new ApiError(404, "No Google app"), {
          details: { kind: "google_oauth_app" },
        });
      }
      return { authorization_url: "https://consent.example" };
    });
    await mount();
    await userEvent.click(
      within(screen.getByRole("group", { name: "Google Calendar" })).getByRole("button", {
        name: "Connect",
      }),
    );
    await userEvent.type(await screen.findByLabelText("Client ID"), "org-app");
    await userEvent.type(screen.getByLabelText("Client secret"), "shh");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/secrets", {
        name: "google-oauth-app",
        description: "Google OAuth client for connected accounts",
        value: { kind: "google_oauth_app", client_id: "org-app", client_secret: "shh" },
        visibility: "org",
      }),
    );
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenLastCalledWith(
        "/me/mcp-connections/oauth/start",
        expect.objectContaining({ url: "https://calendarmcp.googleapis.com/mcp/v1" }),
      ),
    );
    const restart = vi.mocked(apiClient.post).mock.calls.at(-1)?.[1] as Record<string, unknown>;
    expect(restart).not.toHaveProperty("client_id");
    expect(restart).not.toHaveProperty("client_secret");
  });

  it("rotates the org's Google app in place when an admin saves it again", async () => {
    // The first save made the app; a second save must not add a second secret
    // with the same name, the server refuses that. It patches the one there is.
    catalogEntries = [
      ...CATALOG.items,
      {
        ...CATALOG.items[1]!,
        key: "google-calendar",
        name: "Google Calendar",
        url: "https://calendarmcp.googleapis.com/mcp/v1",
        docs_url:
          "https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
      },
    ];
    let startCalls = 0;
    vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
      if (path === "/secrets") {
        throw new ApiError(409, "A secret named 'google-oauth-app' already exists", {
          error: {
            code: "ALREADY_EXISTS",
            message: "A secret named 'google-oauth-app' already exists",
          },
        });
      }
      startCalls += 1;
      if (startCalls === 1) {
        throw Object.assign(new ApiError(404, "No Google app"), {
          details: { kind: "google_oauth_app" },
        });
      }
      return { authorization_url: "https://consent.example" };
    });
    vi.mocked(apiClient.patch).mockResolvedValue({});
    await mount();
    // `serve` routes the other GETs; the secrets list is the one this save reads.
    const served = vi.mocked(apiClient.get).getMockImplementation();
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path !== "/secrets") return served!(path);
      return {
        items: [
          { id: "other", name: "slack", kind: "api_key" },
          { id: "org-app-1", name: "google-oauth-app", kind: "google_oauth_app" },
        ],
        total: 2,
      };
    });
    await userEvent.click(
      within(screen.getByRole("group", { name: "Google Calendar" })).getByRole("button", {
        name: "Connect",
      }),
    );
    await userEvent.type(await screen.findByLabelText("Client ID"), "org-app-2");
    await userEvent.type(screen.getByLabelText("Client secret"), "rotated");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/secrets/org-app-1", {
        value: { kind: "google_oauth_app", client_id: "org-app-2", client_secret: "rotated" },
      }),
    );
    expect(apiClient.get).toHaveBeenCalledWith("/secrets");
  });

  it("keeps a member's own client on their personal connection, not the org's", async () => {
    // A member without mcp:manage cannot write the org's app, so the client they
    // type is spent for their own connection only, as it was before.
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });
    await mount({ canManageOrganization: false });

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    await userEvent.type(screen.getByLabelText("Client ID"), "member-app");
    await userEvent.type(screen.getByLabelText("Client secret"), "mine");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections/oauth/start", {
        name: "github",
        url: "https://api.githubcopilot.com/mcp/",
        catalog_key: "github",
        client_id: "member-app",
        client_secret: "mine",
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalledWith("/secrets", expect.anything());
  });

  it("opens a Google connect link straight to consent, with no client fields", async () => {
    catalogEntries = [
      ...CATALOG.items,
      {
        ...CATALOG.items[1]!,
        key: "google-calendar",
        name: "Google Calendar",
        url: "https://calendarmcp.googleapis.com/mcp/v1",
        docs_url:
          "https://developers.google.com/workspace/calendar/api/guides/configure-mcp-server",
      },
    ];
    window.history.replaceState({}, "", "/mcp-servers?connect=google-calendar");
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });
    await mount();
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/me/mcp-connections/oauth/start",
        expect.not.objectContaining({ client_id: expect.anything() }),
      ),
    );
    expect(screen.queryByLabelText("Client ID")).toBeNull();
    expect(window.location.search).toBe("");
  });

  it("offers the client fields only once OAuth is chosen, and only for a new connection", async () => {
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    expect(screen.queryByLabelText("Client ID")).toBeNull();

    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    expect(screen.getByLabelText("Client ID")).toBeInTheDocument();
    expect(screen.getByLabelText("Client secret")).toBeInTheDocument();
  });

  it("starts the consent with a client registered by hand, for a server that registers none", async () => {
    // HubSpot's remote server publishes no registration endpoint, so the start
    // used to end at "This server rejected the client registration request"
    // with no field anywhere to say which client to use instead (#1620 added the
    // backend half; this is the dialog's).
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: /^My own account/ }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    await userEvent.type(screen.getByLabelText("Client ID"), "app-1");
    await userEvent.type(screen.getByLabelText("Client secret"), "shh");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections/oauth/start", {
        name: "github",
        url: "https://api.githubcopilot.com/mcp/",
        catalog_key: "github",
        client_id: "app-1",
        client_secret: "shh",
      }),
    );
  });

  it("refuses a client secret with no client ID before any request", async () => {
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    await userEvent.type(screen.getByLabelText("Client secret"), "shh");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    expect(apiClient.post).not.toHaveBeenCalled();
    const { toast } = await import("sonner");
    expect(toast.error).toHaveBeenCalledWith("A client secret needs the client ID it belongs to.");
    // The dialog stays open, with what was typed still in it.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("sends a personal connection to the personal endpoint, with its catalog key", async () => {
    // The key is what a binding to each person's own account matches the
    // connection on. Created without it, the connection could never be reached
    // by the agent that asked for it.
    await mount();
    vi.mocked(apiClient.post).mockResolvedValue(connection());

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: /^My own account/ }));
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections", {
        name: "github",
        url: "https://api.githubcopilot.com/mcp/",
        catalog_key: "github",
      }),
    );
  });

  it("warns, rather than refuses, when the organization signs in", async () => {
    // The cost is real - the grant is the consenting person's at the provider,
    // so losing their access takes the organization's server with it - but a
    // shared service account is a legitimate arrangement, and the earlier
    // refusal made it impossible instead of informed.
    await mount();

    // Through Configure: Connect on a server that signs in goes to the provider.
    const linear = within(screen.getByRole("group", { name: "Linear" }));
    await userEvent.click(
      linear.getByRole("button", { name: "Configure Linear before connecting" }),
    );
    await userEvent.click(screen.getByRole("radio", { name: /^One shared account/ }));
    await userEvent.click(screen.getByRole("button", { name: "More options" }));

    expect(screen.getByRole("radio", { name: "OAuth" })).toBeChecked();
    expect(screen.getByText(/use an account the organization controls/)).toBeInTheDocument();
  });

  it("goes straight to the provider when a catalog server signs in", async () => {
    // Its address, its sign-in and its prefix are the catalog's: a form of
    // pre-filled fields with one button under them was a click spent reading.
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });
    await mount();

    const linear = within(screen.getByRole("group", { name: "Linear" }));
    await userEvent.click(linear.getByRole("button", { name: "Connect" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/me/mcp-connections/oauth/start",
        expect.objectContaining({ name: "linear", catalog_key: "linear" }),
      ),
    );
    // The consent comes back to Linear's accounts, not to the top of the list.
    await waitFor(() =>
      expect(document.cookie).toContain(
        `mcp_oauth_return=${encodeURIComponent("/mcp-servers?server=linear")}`,
      ),
    );
  });

  it("keeps the open server in the address, and opens it from there", async () => {
    window.history.replaceState({}, "", "/mcp-servers?server=github");
    serve([connection()], []);
    render(<McpServerList canManageOrganization />, { wrapper });

    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "GitHub" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(window.location.search).toBe("");

    await openConnections();
    expect(window.location.search).toBe("?server=github");
  });

  it("opens an embedded service without changing the workflow address", async () => {
    window.history.replaceState({}, "", "/workflows/draft?tab=editor");
    serve([connection()], []);
    render(
      <McpServerList canManageOrganization initialServerKey="github" persistSelection={false} />,
      { wrapper },
    );
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("heading", { name: "GitHub" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(window.location.pathname + window.location.search).toBe("/workflows/draft?tab=editor");
    await openConnections();
    expect(window.location.pathname + window.location.search).toBe("/workflows/draft?tab=editor");
  });

  it("follows a disconnect at once, without being closed and opened again", async () => {
    await mount({ org: [connection()] });
    const connections = await openConnections();
    await userEvent.click(connections.getByRole("button", { name: /^More for / }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
    const confirm = (await screen.findByText(/Disconnect "github"\?/)).closest(
      '[role="dialog"], [role="alertdialog"]',
    ) as HTMLElement;

    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    serve([], []);
    await userEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: /^More for / })).toBeNull());
  });

  it("opens the form from Configure with its catalog settings folded away", async () => {
    // Who connects and who may use it are the decisions; the address and the
    // names under the fold are the catalog's, and only asked for on request.
    await mount();

    await userEvent.click(
      within(githubRow()).getByRole("button", { name: "Configure GitHub before connecting" }),
    );
    expect(screen.queryByLabelText("Server URL")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "More options" }));
    expect(await screen.findByLabelText("Server URL")).toHaveValue(
      "https://api.githubcopilot.com/mcp/",
    );
  });

  it("lets a member without connections:manage read the organization column, not write it", async () => {
    // Read access is deliberate: an agent author has to see what the Builder
    // will offer. A button that always 403s is worse than no button.
    await mount({ canManageOrganization: false, org: [connection({ name: "gh-org" })] });

    const dialog = await openConnections();

    // Readable - an agent author has to see what the Builder will offer.
    expect(dialog.getByText("gh-org")).toBeInTheDocument();
    // But nothing that writes it. A button that always 403s is worse than none.
    expect(dialog.queryByRole("button", { name: "More for gh-org" })).toBeNull();
  });

  it("shows a server nobody curated rather than hiding it", async () => {
    // A live credential reachable from no screen is a credential nobody can
    // revoke - which is what deleting the second page would otherwise create.
    // No `catalog_key`: this is a personal record, and one carrying GitHub's
    // key would be folded onto the GitHub row instead of getting its own.
    const crm = connection({
      catalog_key: null,
      id: "p9",
      name: "internal-crm",
      url: "https://crm.internal/mcp",
    });
    await mount({ own: [crm] });

    expect(screen.getByText("internal-crm")).toBeInTheDocument();
    expect(
      within(screen.getByRole("group", { name: "internal-crm" })).getByText("Your account"),
    ).toBeInTheDocument();
  });

  it("marks each card with the service's own logo", async () => {
    // The regression this fixes: a catalog laid out as a grid is only scannable
    // if the marks differ, and every card carried the same generic icon. Asserted
    // as "GitHub's card and Linear's card draw different glyphs" rather than on a
    // class name, because that is the property a reader actually depends on.
    await mount();

    const mark = (server: string) =>
      screen.getByRole("group", { name: server }).querySelector("img")?.getAttribute("src");

    expect(mark("GitHub")).toBeTruthy();
    expect(mark("Linear")).toBeTruthy();
    expect(mark("GitHub")).not.toBe(mark("Linear"));
  });

  it("falls back to a monogram for a server the catalog has never heard of", async () => {
    // The case that looks broken when it regresses. A connection added by URL
    // has no catalog key and no brand mark anywhere, so the card shows a
    // bordered initial - the same fallback the vault uses for a provider with
    // no logo. A blank square or a broken image would read as a failed load.
    const crm = connection({
      catalog_key: null,
      id: "p9",
      name: "internal-crm",
      url: "https://crm.internal/mcp",
    });
    await mount({ own: [crm] });

    // The mark slot is the card's first element, and it is decorative either
    // way - so this is the mark, not one of the icons inside the buttons below.
    const mark = screen.getByRole("group", { name: "internal-crm" }).querySelector("[aria-hidden]");

    expect(mark?.tagName).toBe("SPAN");
    expect(mark?.textContent).toBe("i");
  });

  it("draws the mark as a glyph where there is one, and only then", async () => {
    // The other half of the fallback: a curated server must not get the
    // monogram treatment, or the two cases would be indistinguishable and the
    // test above would pass against a page with no logos at all.
    await mount();

    // GitHub's address has a baked logo, so it is drawn in its own colours.
    const logo = screen.getByRole("group", { name: "GitHub" }).querySelector("[aria-hidden]");
    expect(logo?.tagName).toBe("IMG");
    expect(logo?.getAttribute("src")).toMatch(/^data:image\//);
    expect(logo?.textContent).not.toBe("G");
  });

  it("narrows the grid to what was searched for", async () => {
    // Fifty-nine cards is past the point where scanning works, and the catalog
    // only grows. Matching the description too is deliberate: somebody looking
    // for issue tracking does not know the product is called Linear.
    await mount();

    await userEvent.type(screen.getByLabelText("Search servers…"), "pull requests");

    expect(screen.getByRole("group", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Linear" })).toBeNull();
  });

  it("narrows to servers asking for one kind of sign-in (#2103)", async () => {
    await mount();
    const tokenOnly = CATALOG.items.find((entry) => entry.auth === "token");
    const oauthOnly = CATALOG.items.find((entry) => entry.auth === "oauth");
    expect(tokenOnly && oauthOnly).toBeTruthy();

    await userEvent.click(screen.getByLabelText("Sign-in"));
    await userEvent.click(screen.getByRole("option", { name: "OAuth" }));

    expect(await screen.findByRole("group", { name: oauthOnly!.name })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: tokenOnly!.name })).toBeNull();
  });

  it("filters to what somebody has actually connected", async () => {
    // The question this answers on a catalog page: which of these are live?
    // Reading it off fifty-nine cards is the thing the filter replaces.
    await mount({ org: [connection()] });

    await userEvent.click(screen.getByLabelText("Connection state"));
    await userEvent.click(screen.getByRole("option", { name: "Connected" }));

    expect(screen.getByRole("group", { name: "GitHub" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Linear" })).toBeNull();
  });

  it("disconnects through a dialog, and a second confirm during the DELETE is a no-op", async () => {
    // The lone holdout on window.confirm carried the three regressions the other
    // destructive controls were migrated off it to fix: an untranslatable native
    // prompt, a non-accessible modal, and - the real bite - no busy guard, so a
    // double-click fired a second DELETE. The guard is what this pins.
    await mount({ org: [connection()] });

    const connections = await openConnections();
    await userEvent.click(connections.getByRole("button", { name: /^More for / }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));

    // A real dialog, not window.confirm, and its description names the server.
    // Two are open by now - the connections modal underneath it - so the confirm
    // is found by its own words rather than by a role there are two of.
    const dialog = (await screen.findByText(/Disconnect "github"\?/)).closest(
      '[role="dialog"], [role="alertdialog"]',
    ) as HTMLElement;

    // Hold the DELETE in flight so the busy guard is observable: the confirm
    // button disables itself, so the second click cannot fire a second DELETE.
    let release: () => void = () => {};
    vi.mocked(apiClient.delete).mockImplementation(
      () => new Promise((resolve) => (release = () => resolve(undefined))),
    );
    const confirm = within(dialog).getByRole("button", { name: "Disconnect" });
    await userEvent.click(confirm);
    await userEvent.click(confirm);

    expect(apiClient.delete).toHaveBeenCalledTimes(1);
    expect(apiClient.delete).toHaveBeenCalledWith("/mcp-connections/o1");
    release();
  });

  it("renders no remote asset for a logo", async () => {
    // Marks are compiled in. This page must not reach a third party to draw a
    // brand logo: a self-hosted deployment may have no outbound network, and a
    // request keyed on a brand domain tells that third party what is being
    // looked at. The favicon-service fallback this replaces did both.
    await mount({ org: [connection()] });

    // The colour logos are baked into the bundle as data URIs.
    const sources = [...document.querySelectorAll("img")].map((img) => img.getAttribute("src"));
    expect(sources.length).toBeGreaterThan(0);
    for (const src of sources) expect(src).toMatch(/^data:image\//);
  });
});

describe("several accounts on one server", () => {
  /**
   * The half #1341 left open, finished. An organization may hold a read-only
   * GitHub and an admin one; the page could neither create the second nor show
   * it under its own entry, and once both scopes were filled the Connect button
   * disappeared entirely.
   */
  it("offers to connect from the card however many accounts exist", async () => {
    await mount({
      org: [connection({ id: "o1", name: "github" })],
      own: [connection({ id: "p1", name: "github" })],
    });

    expect(within(githubRow()).getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("names every account, so two are never one", async () => {
    await mount({
      org: [
        connection({ id: "o1", name: "gh-readonly" }),
        connection({ id: "o2", name: "gh-admin" }),
      ],
    });

    // One card, whatever it holds.
    expect(screen.getAllByRole("group", { name: "GitHub" })).toHaveLength(1);
    expect(
      within(githubRow()).getByRole("button", { name: "Manage 2 connections on GitHub" }),
    ).toHaveTextContent("2");

    const dialog = await openConnections();
    expect(dialog.getByText("gh-readonly")).toBeInTheDocument();
    expect(dialog.getByText("gh-admin")).toBeInTheDocument();
  });

  it("seeds a name nothing holds yet, so the first submit is not a conflict", async () => {
    await mount({ org: [connection({ id: "o1", name: "github" })] });

    const dialog = await openConnections();
    // The organization's section, where `github` is already taken.
    await userEvent.click(dialog.getByRole("button", { name: "Add account" }));

    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    expect(await screen.findByLabelText("Tool prefix")).toHaveValue("github-2");
  });

  it("seeds the tool prefix with a slug, never a namespaced registry key", async () => {
    // `com.example/thing` is not a valid prefix, so seeding the field with it
    // made a submit that could never pass while `hubspot` happened to work (#1628).
    registryResults = [registryEntry()];
    await mount();

    const row = within(screen.getByRole("group", { name: "Some Thing" }));
    await userEvent.click(row.getByRole("button", { name: "Connect" }));

    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    expect(await screen.findByLabelText("Tool prefix")).toHaveValue("thing");
  });

  it("says where each owner's accounts can be used, which is the whole distinction", async () => {
    await mount({ org: [connection({ name: "gh-org" })] });

    const dialog = await openConnections();

    expect(dialog.getByText("The only kind an agent can be bound to.")).toBeInTheDocument();
    expect(
      dialog.getByText("Yours alone - your chat, and your direct messages in a channel."),
    ).toBeInTheDocument();
  });
});

describe("which of a member's own accounts an agent speaks as", () => {
  /**
   * A binding flagged "speak as whoever is running it" substitutes the runner's
   * own connection for the organization's. With two accounts on one service it
   * declined to guess, and there was nowhere to say which was meant (#1342).
   */
  const TWO = [
    connection({ id: "p1", name: "notion-work" }),
    connection({ id: "p2", name: "notion-side" }),
  ];

  it("offers the choice where the member holds more than one", async () => {
    await mount({ own: TWO });
    const dialog = await openConnections();

    expect(dialog.getAllByLabelText("Main account for agents")).toHaveLength(2);
  });

  it("offers nothing where there is no choice to make", async () => {
    // A single account is substituted whether or not it is marked, so a switch
    // beside it would be a control that changes nothing.
    await mount({ own: [connection({ id: "p1", name: "notion" })] });
    const dialog = await openConnections();

    expect(dialog.queryByLabelText("Main account for agents")).toBeNull();
  });

  it("offers nothing for a connection with no catalog key", async () => {
    // It lands on this row because `entryForConnection` also matches on URL,
    // but the substitution joins on the key - and without one there is nothing
    // to nominate it against. Publish refuses the same combination.
    await mount({
      own: [
        connection({ id: "p1", name: "gh-work" }),
        connection({ id: "p2", name: "gh-typed", catalog_key: null }),
      ],
    });
    const dialog = await openConnections();

    expect(dialog.getAllByLabelText("Main account for agents")).toHaveLength(1);
  });

  it("records the nomination against the account it is beside", async () => {
    await mount({ own: TWO });
    // The hook patches its cache with what the write answered, so a bare mock
    // would fault after the assertion and surface as an unhandled rejection.
    vi.mocked(apiClient.patch).mockResolvedValue({ ...TWO[1], is_default: true });
    const dialog = await openConnections();

    const [, side] = dialog.getAllByLabelText("Main account for agents");
    await userEvent.click(side!);

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/me/mcp-connections/p2", {
        is_default: true,
      }),
    );
  });

  it("shows which one is nominated", async () => {
    await mount({
      own: [
        connection({ id: "p1", name: "notion-work", is_default: true }),
        connection({ id: "p2", name: "notion-side" }),
      ],
    });
    const dialog = await openConnections();

    const boxes = dialog.getAllByLabelText("Main account for agents");
    expect(boxes[0]).toBeChecked();
    expect(boxes[1]).not.toBeChecked();
  });
});

describe("naming a connection something a person can read", () => {
  /**
   * `name` is the tool prefix - lowercase, hyphens, unique per owner - which
   * makes it a poor label: an organization with two Notion accounts chooses
   * between `notion` and `notion-2`, and neither says which workspace it
   * reaches. `label` is what a person reads, and the slug stays beside it.
   */
  // Its own, because the file's `clearAllMocks` lives inside the first
  // `describe` and these are siblings of it - so call history otherwise carries
  // from one test here into the next, and a "was this sent" assertion reads a
  // neighbour's request.
  beforeEach(() => vi.clearAllMocks());

  it("shows the label a person set, with the slug still beside it", async () => {
    await mount({
      own: [
        connection({ id: "p1", name: "notion", label: "Marketing workspace" }),
        connection({ id: "p2", name: "notion-2", label: null }),
      ],
    });
    const dialog = await openConnections();

    expect(dialog.getByText("Marketing workspace")).toBeInTheDocument();
    // Never the label alone: a run's tool calls are recorded under the prefix,
    // so hiding it leaves "why did it call `notion_search`" unanswerable here.
    expect(dialog.getByText("notion")).toBeInTheDocument();
    // And a connection nobody labelled reads exactly as it always did.
    expect(dialog.getByText("notion-2")).toBeInTheDocument();
  });

  it("sends a label typed on the way in", async () => {
    await mount({ org: [] });
    vi.mocked(apiClient.post).mockResolvedValue(connection({ id: "o9", name: "notion" }));

    await within(githubRow()).getByRole("button", { name: "Connect" }).click();
    const form = within(await screen.findByRole("dialog"));
    await userEvent.click(form.getByRole("radio", { name: /^One shared account/ }));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.type(form.getByLabelText("Name"), "  Marketing workspace  ");
    await userEvent.click(form.getByRole("button", { name: /Connect/ }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/mcp-connections",
        // Trimmed by the service; the client sends what was typed minus the ends.
        expect.objectContaining({ label: "Marketing workspace" }),
      ),
    );
  });

  it("offers a custom server's tool prefix from its name until the prefix is edited", async () => {
    // A hand-typed server has no catalog key, so the prefix used to start
    // empty and every custom connection needed the same name typed twice.
    await mount();

    await userEvent.click(screen.getByRole("button", { name: "Add a custom server" }));
    const form = within(await screen.findByRole("dialog"));
    expect(
      form.getByRole("heading", { name: "Add an MCP server for the organization" }),
    ).toBeInTheDocument();

    await userEvent.type(form.getByLabelText("Name"), "Company Wiki");
    expect(form.getByLabelText("Tool prefix")).toHaveValue("company-wiki");

    await userEvent.clear(form.getByLabelText("Tool prefix"));
    await userEvent.type(form.getByLabelText("Tool prefix"), "kb");
    await userEvent.type(form.getByLabelText("Name"), " EU");
    expect(form.getByLabelText("Tool prefix")).toHaveValue("kb");
  });

  it("leaves a catalog server's prefix alone while its name is typed", async () => {
    await mount();

    await userEvent.click(within(githubRow()).getByRole("button", { name: "Connect" }));
    const form = within(await screen.findByRole("dialog"));
    await userEvent.click(await screen.findByRole("button", { name: "More options" }));
    await userEvent.type(form.getByLabelText("Name"), "Company Wiki");

    expect(form.getByLabelText("Tool prefix")).toHaveValue("github");
  });

  it("sends nothing for a label left empty", async () => {
    // An absent label is not `""`: the connection shows its slug, which is what
    // it did before this field existed.
    await mount({ org: [] });
    vi.mocked(apiClient.post).mockResolvedValue(connection({ id: "o9", name: "github" }));

    await within(githubRow()).getByRole("button", { name: "Connect" }).click();
    const form = within(await screen.findByRole("dialog"));
    await userEvent.click(form.getByRole("radio", { name: /^One shared account/ }));
    await userEvent.click(form.getByRole("button", { name: /Connect/ }));

    // The create, not the probe `handleTools` fires straight after it.
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections", expect.anything()),
    );
    const [, body] = vi
      .mocked(apiClient.post)
      .mock.calls.find(([path]) => path === "/mcp-connections")!;
    expect(body).not.toHaveProperty("label");
  });

  it("clears a label by emptying the field, rather than leaving it alone", async () => {
    // `""` is what removes one. Treating an emptied field as "nothing to say"
    // would make a label impossible to take back.
    await mount({
      own: [connection({ id: "p1", name: "notion", label: "Marketing workspace" })],
    });
    vi.mocked(apiClient.patch).mockResolvedValue(connection({ id: "p1", name: "notion" }));
    const dialog = await openConnections();

    await userEvent.click(dialog.getByRole("button", { name: "More for Marketing workspace" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Edit" }));
    const form = within(await screen.findByRole("dialog"));
    await userEvent.clear(form.getByLabelText("Name"));
    await userEvent.click(form.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(
        "/me/mcp-connections/p1",
        expect.objectContaining({ label: "" }),
      ),
    );
  });

  it("seeds the field from the label a connection already has", async () => {
    await mount({
      own: [connection({ id: "p1", name: "notion", label: "Marketing workspace" })],
    });
    const dialog = await openConnections();

    await userEvent.click(dialog.getByRole("button", { name: "More for Marketing workspace" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Edit" }));

    const form = within(await screen.findByRole("dialog"));
    expect(form.getByLabelText("Name")).toHaveValue("Marketing workspace");
  });
  it("finds a registry server in the same list as the catalog", async () => {
    // The point of one list: a server the curated hundred has never heard of is
    // found by typing its name, in the same grid, not on a second screen.
    registryResults = [registryEntry({ name: "Weibo Reader" })];
    await mount();

    await userEvent.type(screen.getByPlaceholderText(/Search/i), "weibo");

    expect(await screen.findByText("Weibo Reader")).toBeVisible();
  });

  it("says on the row that nobody here reviewed it", async () => {
    // Hiding this would be the price of one list: the description is the
    // publisher's and there is no token hint, which matters before somebody
    // pastes a credential into it.
    registryResults = [registryEntry()];
    await mount();

    await userEvent.type(screen.getByPlaceholderText(/Search/i), "thing");

    expect(await screen.findByText("Registry")).toBeVisible();
  });
  it("asks the server for the query rather than filtering in the browser", async () => {
    // The list stopped being one the client holds when 5,703 mirrored servers
    // arrived behind the curated hundred, so the query is a request now.
    await mount();

    await userEvent.type(screen.getByPlaceholderText(/Search/i), "github");

    await waitFor(() => expect(listCalls().some((p) => p.includes("q=github"))).toBe(true));
  });

  it("goes back to the first page when the query changes", async () => {
    // Searching to three results while sitting on page four shows an empty grid
    // under a pager that says there are three.
    await mount();

    await userEvent.type(screen.getByPlaceholderText(/Search/i), "github");

    await waitFor(() =>
      expect(listCalls().some((p) => p.includes("q=github") && p.includes("skip=0"))).toBe(true),
    );
  });

  it("asks the server for the category too", async () => {
    // Filtering a page by category is filtering whatever that page happened to
    // hold, so the category is a request like the query.
    await mount();

    await userEvent.click(screen.getByRole("button", { name: "Filters" }));
    await userEvent.click(screen.getByRole("combobox", { name: /Category/i }));
    await userEvent.click(await screen.findByRole("option", { name: /Development/i }));

    await waitFor(() =>
      expect(listCalls().some((p) => p.includes("category=development"))).toBe(true),
    );
  });

  it("finds a registry server in the same list as the catalog", async () => {
    // One list: a server the curated hundred has never heard of appears in the
    // same grid, not on a second screen.
    registryResults = [registryEntry({ name: "Weibo Reader" })];
    await mount();

    expect(await screen.findByText("Weibo Reader")).toBeVisible();
  });

  it("says on the row that nobody here reviewed it", async () => {
    registryResults = [registryEntry()];
    await mount();

    expect(await screen.findByText("Registry")).toBeVisible();
  });
  it("does not call a connection uncatalogued because its entry is off-page", async () => {
    // Whether a connection is "not in the catalog" is a question about every
    // entry. Asked of a page it answers "yes" for a connection whose entry is on
    // another page - so the GitHub connection below reads as an uncatalogued
    // server the moment a search pushes the GitHub entry out of the page, which
    // is how it appeared at the foot of every page of five thousand.
    await mount({ org: [connection()] });

    await userEvent.type(screen.getByPlaceholderText(/Search/i), "linear");

    await waitFor(() => expect(screen.queryByText("GitHub")).toBeNull());
    expect(screen.queryByText(/not from the catalog/i)).toBeNull();
  });
});

/** Grafana deliberately sits after the first 50 curated entries. */
function multiPageCatalog(): McpCatalogEntry[] {
  return [
    ...CATALOG.items,
    ...Array.from({ length: 54 }, (_, index) =>
      registryEntry({
        key: `server-${index}`,
        name: `Server ${index}`,
        url: `https://server-${index}.example/mcp`,
        category: "development",
        auth: "none",
        reviewed: true,
      }),
    ),
    registryEntry({
      key: "grafana",
      name: "Grafana",
      url: "https://grafana.example/mcp",
      category: "observability",
      reviewed: true,
    }),
  ];
}

function accountFor(entry: McpCatalogEntry, id = entry.key): OrgMcpConnectionRecord {
  return connection({ id, name: entry.key, catalog_key: entry.key, url: entry.url! });
}

async function filterBy(label: string, value: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.click(screen.getByRole("option", { name: value }));
}

describe("connected servers across catalog pages", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    catalogEntries = multiPageCatalog();
  });

  it("finds custom, off-page curated and registry accounts without loading every registry page", async () => {
    const grafana = catalogEntries.at(-1)!;
    const linear = catalogEntries.find((entry) => entry.key === "linear")!;
    registryResults = [registryEntry({ key: "com.example/remote", name: "Remote Registry" })];
    await mount({
      org: [
        accountFor(grafana),
        { ...accountFor(grafana, "grafana-admin"), name: "grafana-admin" },
      ],
      own: [
        { ...accountFor(grafana, "grafana-personal"), name: "grafana-personal" },
        accountFor(linear),
        accountFor(registryResults[0]!),
        connection({ id: "netbox", name: "NetBox", catalog_key: null, url: "https://netbox/mcp" }),
      ],
    });

    expect(screen.queryByRole("group", { name: "Grafana" })).toBeNull();
    expect(screen.queryByRole("group", { name: "NetBox" })).toBeNull();
    await filterBy("Connection state", "Connected");

    expect(await screen.findByRole("group", { name: "Grafana" })).toBeVisible();
    expect(screen.getAllByRole("group", { name: "Grafana" })).toHaveLength(1);
    expect(
      within(screen.getByRole("group", { name: "Grafana" })).getByRole("button", {
        name: "Manage 3 connections on Grafana",
      }),
    ).toBeVisible();
    expect(screen.getByRole("group", { name: "Linear" })).toBeVisible();
    expect(screen.getByRole("group", { name: "Remote Registry" })).toBeVisible();
    expect(screen.getByRole("group", { name: "NetBox" })).toBeVisible();
    expect(screen.getByText("4 servers")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
    expect(
      listCalls().every((path) => new URLSearchParams(path.split("?")[1]).get("skip") === "0"),
    ).toBe(true);
    expect(listCalls().every((path) => path.includes("limit=50"))).toBe(true);

    // Management uses the returned off-page metadata and the real owner account.
    await userEvent.click(
      within(screen.getByRole("group", { name: "Remote Registry" })).getByRole("button", {
        name: "Manage 1 connection on Remote Registry",
      }),
    );
    expect(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "More for com.example/remote",
      }),
    ).toBeVisible();
  });

  it("groups multiple organization and personal accounts into one custom card and preserves permissions", async () => {
    const netbox = { catalog_key: null, url: "https://netbox/mcp" };
    await mount({
      canManageOrganization: false,
      org: [
        connection({ ...netbox, id: "n1", name: "netbox", label: "Shared NetBox" }),
        connection({ ...netbox, id: "n2", name: "netbox-admin", label: "Admin NetBox" }),
      ],
      own: [
        connection({
          ...netbox,
          url: "https://NETBOX/mcp/",
          id: "n3",
          name: "mine",
          label: "My NetBox",
        }),
      ],
    });
    await filterBy("Connection state", "Connected");

    const card = await screen.findByRole("group", { name: "netbox" });
    expect(screen.getAllByRole("group", { name: "netbox" })).toHaveLength(1);
    expect(screen.getByText("1 server")).toBeVisible();
    await userEvent.click(
      within(card).getByRole("button", { name: "Manage 3 connections on netbox" }),
    );
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText("Shared NetBox")).toBeVisible();
    expect(dialog.getByText("Admin NetBox")).toBeVisible();
    expect(dialog.getByText("My NetBox")).toBeVisible();
    expect(dialog.queryByRole("button", { name: "More for Shared NetBox" })).toBeNull();
    expect(dialog.queryByRole("button", { name: "More for Admin NetBox" })).toBeNull();
    expect(dialog.getByRole("button", { name: "More for My NetBox" })).toBeVisible();
  });

  it("paginates connected servers rather than accounts and clamps after the final page is removed", async () => {
    const org = catalogEntries.slice(0, 51).map((entry) => accountFor(entry));
    await mount({ org });
    await filterBy("Connection state", "Connected");
    await userEvent.click(await screen.findByRole("button", { name: "Next page" }));
    const last = catalogEntries[50]!;
    const card = await screen.findByRole("group", { name: last.name });
    expect(screen.getAllByRole("group")).toHaveLength(1);
    expect(screen.getByText("51 servers")).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();

    await userEvent.click(
      within(card).getByRole("button", { name: `Manage 1 connection on ${last.name}` }),
    );
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: `More for ${last.key}`,
      }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
    const confirm = (
      await screen.findByText(`Disconnect "${last.key}"?`, { exact: false })
    ).closest('[role="dialog"], [role="alertdialog"]') as HTMLElement;
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    serve(org.slice(0, 50), []);
    await userEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));
    await userEvent.keyboard("{Escape}");

    expect(await screen.findByRole("group", { name: "GitHub" })).toBeVisible();
    expect(screen.getAllByRole("group")).toHaveLength(50);
    expect(screen.getByText("50 servers")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
    expect(screen.queryByRole("group", { name: last.name })).toBeNull();
  });

  it("keeps the remaining custom account open after its first account is disconnected", async () => {
    const first = connection({
      id: "netbox-first",
      name: "netbox",
      catalog_key: null,
      url: "https://netbox/mcp",
    });
    const second = connection({ ...first, id: "netbox-second", name: "netbox-admin" });
    await mount({ org: [first, second] });
    await filterBy("Connection state", "Connected");
    const card = await screen.findByRole("group", { name: "netbox" });
    await userEvent.click(
      within(card).getByRole("button", { name: "Manage 2 connections on netbox" }),
    );
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "More for netbox" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
    const confirm = (await screen.findByText('Disconnect "netbox"?', { exact: false })).closest(
      '[role="dialog"], [role="alertdialog"]',
    ) as HTMLElement;
    serve([second], []);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await userEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));

    await waitFor(() => expect(screen.getAllByRole("dialog")).toHaveLength(1));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByRole("button", { name: "More for netbox-admin" })).toBeVisible();
    expect(dialog.queryByRole("button", { name: "More for netbox" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.getAllByRole("group")).toHaveLength(1);
    expect(screen.getByText("1 server")).toBeVisible();
  });

  it("opens an off-page custom bookmark and refreshes its account group after a disconnect", async () => {
    const key = "custom:https://netbox/mcp";
    window.history.replaceState({}, "", `/mcp-servers?server=${encodeURIComponent(key)}`);
    const first = connection({
      id: "netbox-first",
      name: "netbox",
      catalog_key: null,
      url: "https://netbox/mcp",
    });
    const second = connection({ ...first, id: "netbox-second", name: "netbox-admin" });
    await mount({ org: [first, second] });

    expect(screen.queryByRole("group", { name: "netbox" })).toBeNull();
    const accounts = within(await screen.findByRole("dialog"));
    expect(accounts.getByRole("button", { name: "More for netbox" })).toBeVisible();
    expect(accounts.getByText("netbox-admin")).toBeVisible();
    expect(
      listCalls().some((path) => {
        const params = new URLSearchParams(path.split("?")[1]);
        return params.get("q") === key && params.get("limit") === "10";
      }),
    ).toBe(true);
    await userEvent.click(accounts.getByRole("button", { name: "More for netbox" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
    const confirm = (await screen.findByText('Disconnect "netbox"?', { exact: false })).closest(
      '[role="dialog"], [role="alertdialog"]',
    ) as HTMLElement;
    serve([second], []);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await userEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));

    const remaining = within(await screen.findByRole("dialog"));
    expect(await remaining.findByRole("heading", { name: "netbox-admin" })).toBeVisible();
    expect(remaining.getByRole("button", { name: "More for netbox-admin" })).toBeVisible();
    expect(remaining.queryByRole("button", { name: "More for netbox" })).toBeNull();
    expect(window.location.search).toBe(`?server=${encodeURIComponent(key)}`);
  });

  it("does not open a stale custom bookmark when no account remains", async () => {
    const key = "custom:https://removed.example/mcp";
    window.history.replaceState({}, "", `/mcp-servers?server=${encodeURIComponent(key)}`);
    await mount();

    await waitFor(() =>
      expect(
        listCalls().some((path) => new URLSearchParams(path.split("?")[1]).get("q") === key),
      ).toBe(true),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("group", { name: "GitHub" })).toBeVisible();
  });

  it.each(["unreachable", "broken", "refused", "duplicate"] as const)(
    "reopens a bookmarked %s registry server even though All hides it",
    async (outcome) => {
      const saved = registryEntry({
        key: "com.example/saved",
        name: "Saved registry server",
        check: { outcome, checked_at: "2026-11-03T00:00:00Z", tools: null, read_only_tools: null },
      });
      registryResults = [saved];
      window.history.replaceState({}, "", `/mcp-servers?server=${encodeURIComponent(saved.key)}`);
      const account = { ...accountFor(saved, "saved-account-id"), name: "saved-account" };

      await mount({ own: [account] });

      const dialog = within(await screen.findByRole("dialog"));
      expect(dialog.getByRole("heading", { name: saved.name })).toBeVisible();
      expect(dialog.getByRole("button", { name: "More for saved-account" })).toBeVisible();
      expect(screen.queryByRole("group", { name: saved.name })).toBeNull();
      expect(
        listCalls().some((path) => {
          const params = new URLSearchParams(path.split("?")[1]);
          return params.get("q") === saved.key && params.get("state") === "connected";
        }),
      ).toBe(true);
    },
  );

  it.each(["search", "category", "sign-in", "state"] as const)(
    "resets a real second page when the %s filter changes",
    async (filter) => {
      await mount({ org: catalogEntries.map((entry) => accountFor(entry)) });
      await userEvent.click(screen.getByRole("button", { name: "Next page" }));
      await screen.findByRole("group", { name: "Grafana" });
      const previousCalls = listCalls().length;

      if (filter === "search")
        await userEvent.type(screen.getByLabelText("Search servers…"), "GitHub");
      if (filter === "category") await filterBy("Category", "project management");
      if (filter === "sign-in") await filterBy("Sign-in", "OAuth");
      if (filter === "state") await filterBy("Connection state", "Connected");

      await waitFor(() => {
        const calls = listCalls().slice(previousCalls);
        expect(calls.length).toBeGreaterThan(0);
        expect(calls.every((path) => path.includes("skip=0"))).toBe(true);
      });
      expect(
        await screen.findByRole("group", {
          name: filter === "category" || filter === "sign-in" ? "Linear" : "GitHub",
        }),
      ).toBeVisible();
      if (filter === "state")
        expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
      else expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
    },
  );

  it("combines Connected with search, category and sign-in and counts filtered servers", async () => {
    await mount({
      org: [accountFor(catalogEntries.at(-1)!)],
      own: [connection({ id: "n1", name: "netbox", catalog_key: null, url: "https://netbox/mcp" })],
    });
    await filterBy("Connection state", "Connected");
    await filterBy("Category", "custom");
    await filterBy("Sign-in", "API token");
    await userEvent.type(screen.getByLabelText("Search servers…"), "netbox");

    expect(await screen.findByRole("group", { name: "netbox" })).toBeVisible();
    expect(screen.getByText("1 server")).toBeVisible();
    expect(screen.queryByRole("group", { name: "Grafana" })).toBeNull();
    await filterBy("Connection state", "Not connected");
    await waitFor(() => expect(screen.queryByRole("group", { name: "netbox" })).toBeNull());
    expect(screen.getByText("0 servers")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Next page" })).toBeNull();
  });
});

describe("arriving with ?connect=<catalog key>", () => {
  /**
   * The link an agent hands somebody whose own account a personal binding
   * needs: the backend writes it, so what the parameter is called is a contract
   * between the two. It opens the *personal* connect flow for that server and
   * is stripped as it is read, so a reload does not reopen a dialog somebody
   * closed.
   */
  it("opens the personal connect dialog for the named server", async () => {
    window.history.replaceState({}, "", "/mcp-servers?connect=github");

    await mount();

    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("radio", { name: /^My own account/ })).toBeChecked();
    expect(window.location.search).toBe("");
  });

  it("says so when the catalog holds no such server", async () => {
    const { toast } = await import("sonner");
    window.history.replaceState({}, "", "/mcp-servers?connect=no-such-server");

    await mount();

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "No server in the catalog is called no-such-server.",
      ),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(window.location.search).toBe("");
  });
});

describe("arriving with ?connect= for a server behind OAuth", () => {
  it("starts the personal consent with the catalog key, so the connection can be matched", async () => {
    // The key is what a binding to each person's own account finds the
    // connection by. The callback creates the row from the staged flow, so the
    // key has to travel with the start request or the row never carries one.
    vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://consent.example" });
    window.history.replaceState({}, "", "/mcp-servers?connect=linear");

    await mount();

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections/oauth/start", {
        name: "linear",
        url: "https://mcp.linear.app/sse",
        catalog_key: "linear",
      }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
