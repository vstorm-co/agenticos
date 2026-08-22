import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePortals } from "./use-portals";
import { apiClient } from "@/lib/api-client";
import type { PortalCatalogEntry } from "@/types/portals";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function githubPortal(overrides: Partial<PortalCatalogEntry> = {}): PortalCatalogEntry {
  return {
    key: "github",
    name: "GitHub",
    description: "Run an agent when something happens in a repository.",
    category: "development",
    icon: "github",
    event_source: "github",
    delivery: "auto_webhook",
    webhook_admin_scopes: ["admin:repo_hook"],
    target_kind: "repo",
    connection_catalog_key: "github",
    connection_id: null,
    connection_state: null,
    connection_covers_webhook_scopes: false,
    connect_blocked_by: null,
    oauth_app_kind: "github_oauth_app",
    presets: [{ key: "issue_opened", label: "New issue", description: "…", target_required: true }],
    ...overrides,
  };
}

const EMAIL_PORTAL: PortalCatalogEntry = {
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
  presets: [{ key: "any_email", label: "Any email", description: "…", target_required: false }],
};

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

function serve(github: PortalCatalogEntry, manageable = true) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/trigger-portals") return { items: [github, EMAIL_PORTAL], total: 2 };
    if (path === "/agents/mcp-catalog") return MCP_CATALOG;
    // The management-only listings: a caller without mcp:manage gets a 403 here,
    // which must cost them nothing the portal grid decides by.
    if (path === "/mcp-connections") {
      if (!manageable) throw new Error("403");
      return { items: [], total: 0 };
    }
    if (path === "/me/mcp-connections") return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

async function run(github: PortalCatalogEntry, manageable = true) {
  serve(github, manageable);
  const { result } = renderHook(() => usePortals(), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  await waitFor(() => expect(result.current.items.length).toBeGreaterThan(0));
  return result;
}

describe("usePortals", () => {
  beforeEach(() => vi.clearAllMocks());

  it("asks an auto-webhook portal with no connection to connect the account", async () => {
    const result = await run(githubPortal());
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("connect");
    expect(github?.connectionId).toBeNull();
  });

  it("creates when the catalog says connected and the grant covers the scope", async () => {
    const result = await run(
      githubPortal({
        connection_id: "o1",
        connection_state: "connected",
        connection_covers_webhook_scopes: true,
      }),
    );
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("create");
    expect(github?.connectionId).toBe("o1");
    expect(github?.serverUrl).toBe("https://api.githubcopilot.com/mcp/");
  });

  it("decides create off the catalog even when the connection listing is refused", async () => {
    // The whole point of the state riding on the catalog: a Member whose run
    // grant authorizes the create cannot read the mcp:manage-gated listing, and
    // that 403 must not turn a connected portal back into "connect".
    const result = await run(
      githubPortal({
        connection_id: "o1",
        connection_state: "connected",
        connection_covers_webhook_scopes: true,
      }),
      false,
    );
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("create");
    expect(github?.connectionId).toBe("o1");
  });

  it("asks to re-authorize when connected but the grant lacks the webhook scope", async () => {
    const result = await run(
      githubPortal({
        connection_id: "o1",
        connection_state: "connected",
        connection_covers_webhook_scopes: false,
        connect_blocked_by: null,
      }),
    );
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("reauthorize");
  });

  it("asks to re-authorize when the connection has not finished consent", async () => {
    const result = await run(
      githubPortal({ connection_id: "o1", connection_state: "needs_authorization" }),
    );
    const github = result.current.items.find((item) => item.portal.key === "github");
    expect(github?.action).toBe("reauthorize");
  });

  it("lets a manual portal create a trigger with no connection at all", async () => {
    const result = await run(githubPortal());
    const email = result.current.items.find((item) => item.portal.key === "email");
    expect(email?.action).toBe("create");
    expect(email?.connectionId).toBeNull();
  });
});

function gmailPortal(overrides: Partial<PortalCatalogEntry> = {}): PortalCatalogEntry {
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
    connect_blocked_by: null,
    oauth_app_kind: "google_oauth_app",
    presets: [{ key: "any_message", label: "Any", description: "…", target_required: false }],
    ...overrides,
  };
}

async function actionOf(portal: PortalCatalogEntry): Promise<string | undefined> {
  const result = await run(portal);
  return result.current.items.find((item) => item.portal.key === portal.key)?.action;
}

describe("a polled portal needs a connected account", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers Connect rather than Create when nobody has connected it", async () => {
    // It offered Create, on the reading that a polling portal "wires its own
    // delivery" - so two Gmail triggers were made against a mailbox nobody had
    // connected, and neither could ever fire (#1068).
    expect(await actionOf(gmailPortal())).toBe("connect");
  });

  it("offers Create once the account is connected and working", async () => {
    expect(
      await actionOf(gmailPortal({ connection_id: "c1", connection_state: "connected" })),
    ).toBe("create");
  });

  it("offers Re-authorize for a grant that is not usable yet", async () => {
    expect(
      await actionOf(gmailPortal({ connection_id: "c1", connection_state: "needs_authorization" })),
    ).toBe("reauthorize");
  });

  it("does not ask it for a webhook scope it never registers", async () => {
    // A polled portal asked for its read scopes at consent and holds them or does
    // not, which `connection_state` already answered - so the webhook-scope test
    // that gates a GitHub card must not gate this one.
    expect(
      await actionOf(
        gmailPortal({
          connection_id: "c1",
          connection_state: "connected",
          connection_covers_webhook_scopes: false,
        }),
      ),
    ).toBe("create");
  });
});
