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
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
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

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/agents") return Promise.resolve({ items: AGENTS, total: AGENTS.length });
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
