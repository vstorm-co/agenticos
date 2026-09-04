import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { McpServerList } from "./mcp-server-list";
import { apiClient } from "@/lib/api-client";
import type { McpCatalogEntry } from "@/types/mcp";
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
    is_default: false,
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
    if (path === "/agents/mcp-catalog") return CATALOG;
    // The paged list, which is the grid. The server joins the curated rows and
    // the registry mirror; here the mock plays both, in that order.
    if (path.startsWith("/agents/mcp-servers")) {
      // Filters and pages the way the endpoint does. A mock that answered every
      // query with everything would make "the grid narrows to what was searched
      // for" a test of the mock.
      const params = new URLSearchParams(path.split("?")[1] ?? "");
      const needle = (params.get("q") ?? "").toLowerCase();
      const skip = Number(params.get("skip") ?? 0);
      const limit = Number(params.get("limit") ?? 50);
      const all = [...CATALOG.items, ...registryResults];
      const matched = needle
        ? all.filter(
            (entry) =>
              entry.name.toLowerCase().includes(needle) ||
              (entry.description ?? "").toLowerCase().includes(needle),
          )
        : all;
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
  beforeEach(() => {
    vi.clearAllMocks();
    registryResults = [];
  });

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
    const crm = connection({
      catalog_key: null,
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

    expect(await screen.findByLabelText("Tool prefix")).toHaveValue("github-2");
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

    expect(dialog.getAllByLabelText("Agents speak as this one")).toHaveLength(2);
  });

  it("offers nothing where there is no choice to make", async () => {
    // A single account is substituted whether or not it is marked, so a switch
    // beside it would be a control that changes nothing.
    await mount({ own: [connection({ id: "p1", name: "notion" })] });
    const dialog = await openConnections();

    expect(dialog.queryByLabelText("Agents speak as this one")).toBeNull();
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

    expect(dialog.getAllByLabelText("Agents speak as this one")).toHaveLength(1);
  });

  it("records the nomination against the account it is beside", async () => {
    await mount({ own: TWO });
    // The hook patches its cache with what the write answered, so a bare mock
    // would fault after the assertion and surface as an unhandled rejection.
    vi.mocked(apiClient.patch).mockResolvedValue({ ...TWO[1], is_default: true });
    const dialog = await openConnections();

    const [, side] = dialog.getAllByLabelText("Agents speak as this one");
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

    const boxes = dialog.getAllByLabelText("Agents speak as this one");
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

  it("sends nothing for a label left empty", async () => {
    // An absent label is not `""`: the connection shows its slug, which is what
    // it did before this field existed.
    await mount({ org: [] });
    vi.mocked(apiClient.post).mockResolvedValue(connection({ id: "o9", name: "github" }));

    await within(githubRow()).getByRole("button", { name: "Connect" }).click();
    const form = within(await screen.findByRole("dialog"));
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

    await userEvent.click(dialog.getByRole("button", { name: "Edit" }));
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

    await userEvent.click(dialog.getByRole("button", { name: "Edit" }));

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
    expect(dialog.getByRole("radio", { name: "You" })).toBeChecked();
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
