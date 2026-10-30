import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Agent, AgentCeiling } from "@/types/agents";
import { Perm, type Permission } from "@/types/permissions";

/**
 * New agent at the deployment's agents-per-organization limit (#2488).
 *
 * The create used to be refused only after the name and audience were filled
 * in, as a toast. At the limit the page now says so before the dialog, and
 * below the limit - or with no limit at all - nothing about New agent changes.
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
  usePathname: () => "/agents",
}));
const rig = vi.hoisted(() => ({ can: (_permission: Permission): boolean => true }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: rig.can }) }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const AGENT: Agent = {
  id: "a1",
  slug: "support",
  name: "Support",
  description: null,
  status: "published",
  visibility: "org",
  owner_user_id: "u1",
  current_version_id: "v1",
  has_avatar: false,
  can_run: true,
  created_at: "2026-07-01T00:00:00Z",
};

/** The ceiling's own route, apart from the paged list. */
const CEILING = "/agents/ceiling";

const NO_LIMIT: AgentCeiling = { limit: null, held: null, at_limit: false };

/** A ceiling the way the route answers it: `at_limit` is the server's to say. */
function limited(limit: number, held: number | null, atLimit: boolean): AgentCeiling {
  return { limit, held, at_limit: atLimit };
}

function listing(ceiling: AgentCeiling, items: Agent[] = [AGENT]) {
  vi.mocked(apiClient.get).mockImplementation((path: string) =>
    Promise.resolve(
      path === CEILING
        ? ceiling
        : path === "/agents"
          ? { items, total: items.length, categories: [], tags: [] }
          : { items: [], total: 0 },
    ),
  );
}

const NOTICE = "This organization is at its agent limit";

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  rig.can = () => true;
});

describe("New agent at the organization's agent limit", () => {
  it("is disabled and names the limit before any dialog opens", async () => {
    listing(limited(1, 1, true));
    render(<AgentsPage />, { wrapper });

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(NOTICE);
    expect(notice).toHaveTextContent("allows 1 agent per organization, and this one has 1");
    const create = screen.getByRole("button", { name: "New agent" });
    expect(create).toBeDisabled();
    // The reason is the button's description, not just text somewhere nearby.
    expect(create).toHaveAccessibleDescription(expect.stringContaining(NOTICE));

    await userEvent.click(create);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("tells a caller who cannot see every agent the limit, not the count", async () => {
    // The count includes agents hidden from a Member, so the server sends none.
    listing(limited(3, null, true));
    render(<AgentsPage />, { wrapper });

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(
      "allows 3 agents per organization, and this one has reached it",
    );
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();
  });

  it("offers no create from an empty gallery either", async () => {
    // The caller sees none of the organization's agents, yet it is at its limit.
    listing(limited(2, 2, true), []);
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("No agents yet")).toBeInTheDocument();
    // Once the limit is known, not merely before it is.
    expect(
      await screen.findByText(/already holds as many as this deployment allows/),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New agent" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();
  });

  it("tells an editor at the limit why the gallery offers no create", async () => {
    listing(limited(2, 2, true), []);
    render(<AgentsPage />, { wrapper });

    expect(
      await screen.findByText(/already holds as many as this deployment allows/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Create one, give it instructions/)).not.toBeInTheDocument();
  });

  it("keeps New agent disabled until the limit is known", async () => {
    // Unknown is not "below the limit": a click in that window used to open a
    // dialog the create would then be refused from.
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === CEILING
        ? new Promise((resolve) => {
            answer = resolve;
          })
        : Promise.resolve({ items: [AGENT], total: 1, categories: [], tags: [] }),
    );
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();

    answer(limited(5, 1, false));
    await waitFor(() => expect(screen.getByRole("button", { name: "New agent" })).toBeEnabled());
  });

  it("shows the limit while the list is still loading", async () => {
    // The ceiling is its own query, not a list page's: a list reloading under a
    // new filter key cannot unset it.
    vi.mocked(apiClient.get).mockImplementation((path: string) =>
      path === CEILING ? Promise.resolve(limited(1, 1, true)) : new Promise(() => {}),
    );
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByRole("status")).toHaveTextContent(NOTICE);
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();
  });

  it("shows a caller who cannot create agents neither the notice nor New agent", async () => {
    rig.can = (permission) => permission !== Perm.agentsEdit;
    listing(limited(1, 1, true));
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New agent" })).not.toBeInTheDocument();
    // No ceiling read either: the route would refuse this caller.
    expect(vi.mocked(apiClient.get).mock.calls.some(([path]) => path === CEILING)).toBe(false);
  });

  it("is unchanged below the limit", async () => {
    listing(limited(5, 4, false));
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    const create = screen.getByRole("button", { name: "New agent" });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("is unchanged when the deployment sets no limit", async () => {
    listing(NO_LIMIT);
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "New agent" })).toBeEnabled());
  });
});
