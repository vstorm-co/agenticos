import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Agent } from "@/types/agents";

/**
 * The agents gallery's status filter.
 *
 * It replaced a segmented control with a Select this session, and it does two
 * things rather than one: it narrows what is rendered, and it decides whether
 * archived agents are *fetched at all*. The second is easy to break while the
 * first still looks right - the list narrows correctly and the archived agents
 * are simply never there, which is indistinguishable from having none.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  // The header's "?" reads the path to decide whether this page has tips.
  usePathname: () => "/agents",
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function agent(name: string, status: Agent["status"]): Agent {
  return {
    id: `${name}-id`,
    slug: name.toLowerCase(),
    name,
    description: null,
    status,
    visibility: "private",
    owner_user_id: "u1",
    current_version_id: status === "published" ? "v1" : null,
    has_avatar: false,
    can_run: false,
    created_at: "2026-07-01T00:00:00Z",
  };
}

const AGENTS = [agent("Live", "published"), agent("Draft", "draft"), agent("Old", "archived")];

/** The category/tag facet the request carried, read out of either params shape. */
function facetOf(options: unknown): { category: string[]; tag: string[] } {
  const params = (options as { params?: Record<string, string> | [string, string][] } | undefined)
    ?.params;
  const pairs = Array.isArray(params)
    ? params
    : Object.entries(params ?? {}).map(([k, v]) => [k, v] as [string, string]);
  return {
    category: pairs.filter(([k]) => k === "category").map(([, v]) => v),
    tag: pairs.filter(([k]) => k === "tag").map(([, v]) => v),
  };
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) => {
    if (path === "/agents") {
      // The server applies the facet, so a non-matching category empties the page.
      const { category } = facetOf(options);
      if (category.length > 0 && !category.includes("sales")) {
        return Promise.resolve({ items: [], total: 0 });
      }
      return Promise.resolve({ items: AGENTS, total: AGENTS.length });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
});

/** The status Select, which has no `htmlFor` label of its own. */
function statusFilter() {
  return screen.getByRole("combobox", { name: "Filter by status" });
}

describe("the agents gallery filter", () => {
  it("shows every status on 'All'", async () => {
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("Old")).toBeInTheDocument();
  });

  it("asks the API for archived agents on 'All', or they could never be shown", async () => {
    // The filtering is client-side, so a request that omitted them would produce
    // a gallery that quietly cannot show an archived agent under any filter.
    render(<AgentsPage />, { wrapper });

    await waitFor(() =>
      expect(vi.mocked(apiClient.get)).toHaveBeenCalledWith("/agents", {
        params: { include_archived: "true" },
      }),
    );
  });

  it("narrows to one status when one is chosen", async () => {
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.click(statusFilter());
    await userEvent.click(screen.getByRole("option", { name: "Drafts" }));

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
    expect(screen.queryByText("Old")).toBeNull();
  });

  it("stops fetching archived agents once they cannot be shown", async () => {
    // The reason the flag is derived from the filter rather than always on: two
    // of the four filters can never render an archived agent, so asking for them
    // is a larger response for nothing.
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.click(statusFilter());
    await userEvent.click(screen.getByRole("option", { name: "Published" }));

    await waitFor(() =>
      expect(vi.mocked(apiClient.get)).toHaveBeenCalledWith("/agents", undefined),
    );
  });

  it("keeps asking for archived agents when Archived is the filter", async () => {
    // The one that would break silently: filter to Archived, do not request them,
    // and the page renders "no agents match" forever.
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.click(statusFilter());
    await userEvent.click(screen.getByRole("option", { name: "Archived" }));

    expect(await screen.findByText("Old")).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
  });

  it("drives the request with the category facet as tuple pairs", async () => {
    // The facet goes to the server so it filters the whole set, not the fetched
    // page - and a repeated key survives only as tuple pairs.
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.type(
      screen.getByRole("textbox", { name: "Filter by category" }),
      "sales{Enter}",
    );

    await waitFor(() => {
      const facets = vi
        .mocked(apiClient.get)
        .mock.calls.filter(([path]) => path === "/agents")
        .map(([, options]) => facetOf(options));
      expect(facets.some((f) => f.category.includes("sales"))).toBe(true);
    });
    // Live is still there: "sales" matches in the mock.
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("changes the query key with the facet, so a new selection is not answered from a stale page", async () => {
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    // A category the mock does not match empties the page - which only happens
    // if the facet actually reached a fresh request rather than a cached one.
    await userEvent.type(
      screen.getByRole("textbox", { name: "Filter by category" }),
      "reports{Enter}",
    );

    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
  });

  it("shows the filter-empty copy, not 'no agents yet', for a zero-match facet", async () => {
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.type(
      screen.getByRole("textbox", { name: "Filter by category" }),
      "reports{Enter}",
    );

    expect(await screen.findByText("Nothing matches")).toBeInTheDocument();
    // The trap this guards: a zero-match server facet reading as an empty account.
    expect(screen.queryByText("No agents yet")).toBeNull();
    expect(screen.queryByText("Nobody has shared an agent with you yet.")).toBeNull();
  });

  it("clears the facet from the empty state, bringing the list back", async () => {
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.type(
      screen.getByRole("textbox", { name: "Filter by category" }),
      "reports{Enter}",
    );
    await screen.findByText("Nothing matches");

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(await screen.findByText("Live")).toBeInTheDocument();
  });

  it("searches by handle as well as by name", async () => {
    // The slug is what the agent is addressed by from Slack and the API, and it
    // is the one string on the card nobody could have typed by accident.
    render(<AgentsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.type(screen.getByLabelText("Search agents"), "draft");

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.queryByText("Live")).toBeNull();
  });
});
