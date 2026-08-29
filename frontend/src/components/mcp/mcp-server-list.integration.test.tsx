import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { McpServerList } from "./mcp-server-list";
import { apiClient } from "@/lib/api-client";
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

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const CATALOG = {
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
    auth_type: "bearer",
    oauth_authorized: false,
    last_status: "ok",
    last_error: null,
    last_checked_at: null,
    catalog_key: "github",
    granted_scopes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** Route each GET to the list it is asking for, so the two owners stay distinct. */
function serve(org: OrgMcpConnectionRecord[], own: McpConnectionRecord[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents/mcp-catalog") return CATALOG;
    if (path === "/mcp-connections") return { items: org, total: org.length };
    if (path === "/me/mcp-connections") return { items: own, total: own.length };
    throw new Error(`unexpected GET ${path}`);
  });
}

/** Open the connections modal for GitHub, where every account is listed. */
async function openConnections() {
  await userEvent.click(within(githubRow()).getByRole("button", { name: /Manage connections on/ }));
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

describe("McpServerList", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps the card to two controls and counts what is behind them", async () => {
    // The card used to grow a chip per connection, so a server with three
    // accounts stood taller than its neighbours and the grid went ragged.
    await mount({ org: [connection()], own: [] });

    const row = within(githubRow());
    expect(row.getByRole("button", { name: "Connect" })).toBeInTheDocument();
    // Labelled for a screen reader, and counted for everybody else.
    expect(row.getByRole("button", { name: "Manage connections on GitHub" })).toHaveTextContent(
      "1 connection",
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
    await userEvent.type(screen.getByLabelText("Access token"), "ghp-secret-9876");
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/mcp-connections", {
        name: "github",
        url: "https://api.githubcopilot.com/mcp/",
        auth_token: "ghp-secret-9876",
        catalog_key: "github",
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
    await userEvent.click(screen.getByRole("radio", { name: "You" }));

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
    await userEvent.click(screen.getByRole("radio", { name: "Organization" }));

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

  it("writes no connection row when OAuth is chosen - the callback does that", async () => {
    // Submitting the form would make an unauthorized bearer connection that then
    // has to be repaired. The grant comes back from the provider first.
    await mount();

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: "You" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    expect(apiClient.post).not.toHaveBeenCalledWith("/me/mcp-connections", expect.anything());
  });

  it("sends a personal connection to the personal endpoint, without a catalog key", async () => {
    // The two endpoints take different bodies. `catalog_key` is a column the
    // personal one does not have, and sending it would 422 the whole request.
    await mount();
    vi.mocked(apiClient.post).mockResolvedValue(connection());

    const row = within(githubRow());
    await userEvent.click(row.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: "You" }));
    await userEvent.click(screen.getByRole("button", { name: "Connect & check" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/me/mcp-connections", {
        name: "github",
        url: "https://api.githubcopilot.com/mcp/",
      }),
    );
  });

  it("warns, rather than refuses, when the organization signs in", async () => {
    // The cost is real - the grant is the consenting person's at the provider,
    // so losing their access takes the organization's server with it - but a
    // shared service account is a legitimate arrangement, and the earlier
    // refusal made it impossible instead of informed.
    await mount();

    const linear = within(screen.getByRole("group", { name: "Linear" }));
    await userEvent.click(linear.getByRole("button", { name: "Connect" }));
    await userEvent.click(screen.getByRole("radio", { name: "Organization" }));
    await userEvent.click(screen.getByRole("radio", { name: "OAuth" }));

    expect(screen.getByText(/use an account the organization controls/)).toBeInTheDocument();
  });

  it("lets a member without connections:manage read the organization column, not write it", async () => {
    // Read access is deliberate: an agent author has to see what the Builder
    // will offer. A button that always 403s is worse than no button.
    await mount({ canManageOrganization: false, org: [connection({ name: "gh-org" })] });

    const dialog = await openConnections();

    // Readable - an agent author has to see what the Builder will offer.
    expect(dialog.getByText("gh-org")).toBeInTheDocument();
    // But nothing that writes it. A button that always 403s is worse than none.
    expect(dialog.queryByRole("button", { name: "Disconnect" })).toBeNull();
    expect(dialog.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("shows a server nobody curated rather than hiding it", async () => {
    // A live credential reachable from no screen is a credential nobody can
    // revoke - which is what deleting the second page would otherwise create.
    // No `catalog_key`: this is a personal record, and one carrying GitHub's
    // key would be folded onto the GitHub row instead of getting its own.
    const { catalog_key: _ignored, ...crm } = connection({
      id: "p9",
      name: "internal-crm",
      url: "https://crm.internal/mcp",
    });
    await mount({ own: [crm] });

    expect(screen.getByText("internal-crm")).toBeInTheDocument();
    expect(screen.getByText("not in the catalog")).toBeInTheDocument();
  });

  it("marks each card with the service's own logo", async () => {
    // The regression this fixes: a catalog laid out as a grid is only scannable
    // if the marks differ, and every card carried the same generic icon. Asserted
    // as "GitHub's card and Linear's card draw different glyphs" rather than on a
    // class name, because that is the property a reader actually depends on.
    await mount();

    const glyph = (server: string) =>
      screen.getByRole("group", { name: server }).querySelector("svg path")?.getAttribute("d");

    expect(glyph("GitHub")).toBeTruthy();
    expect(glyph("Linear")).toBeTruthy();
    expect(glyph("GitHub")).not.toBe(glyph("Linear"));
  });

  it("falls back to a monogram for a server the catalog has never heard of", async () => {
    // The case that looks broken when it regresses. A connection added by URL
    // has no catalog key and no brand mark anywhere, so the card shows a
    // bordered initial - the same fallback the vault uses for a provider with
    // no logo. A blank square or a broken image would read as a failed load.
    const { catalog_key: _ignored, ...crm } = connection({
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

    const mark = screen.getByRole("group", { name: "GitHub" }).querySelector("[aria-hidden]");

    expect(mark?.tagName).toBe("svg");
    expect(mark?.textContent).not.toBe("G");
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
    await userEvent.click(connections.getByRole("button", { name: "Disconnect" }));

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

    expect(document.querySelectorAll("img")).toHaveLength(0);
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
      within(githubRow()).getByRole("button", { name: /Manage connections/ }),
    ).toHaveTextContent("2 connections");

    const dialog = await openConnections();
    expect(dialog.getByText("gh-readonly")).toBeInTheDocument();
    expect(dialog.getByText("gh-admin")).toBeInTheDocument();
  });

  it("seeds a name nothing holds yet, so the first submit is not a conflict", async () => {
    await mount({ org: [connection({ id: "o1", name: "github" })] });

    const dialog = await openConnections();
    // The organization's section, where `github` is already taken.
    await userEvent.click(dialog.getByRole("button", { name: "Connect another" }));

    expect(await screen.findByLabelText(/name/i)).toHaveValue("github-2");
  });

  it("says where each owner's accounts can be used, which is the whole distinction", async () => {
    await mount({ org: [connection({ name: "gh-org" })] });

    const dialog = await openConnections();

    expect(dialog.getByText("The only kind an agent can be bound to.")).toBeInTheDocument();
    expect(
      dialog.getByText("Yours alone — your chat, and your direct messages in a channel."),
    ).toBeInTheDocument();
  });
});
