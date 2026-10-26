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

function listing(ceiling: AgentCeiling | null, items: Agent[] = [AGENT]) {
  vi.mocked(apiClient.get).mockImplementation((path: string) =>
    Promise.resolve(
      path === "/agents"
        ? { items, total: items.length, categories: [], tags: [], ceiling }
        : { items: [], total: 0 },
    ),
  );
}

const NOTICE = "This organization is at its agent limit";

/** The ceiling's own read: one row, no filters. */
function isCeilingRead(options: unknown) {
  return (options as { params?: Record<string, string> } | undefined)?.params?.limit === "1";
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  rig.can = () => true;
});

describe("New agent at the organization's agent limit", () => {
  it("is disabled and names the limit before any dialog opens", async () => {
    listing({ limit: 1, held: 1 });
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

  it("offers no create from an empty gallery either", async () => {
    // The caller sees none of the organization's agents, yet it is at its limit.
    listing({ limit: 2, held: 2 }, []);
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("No agents yet")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New agent" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();
  });

  it("tells an editor at the limit why the gallery offers no create", async () => {
    listing({ limit: 2, held: 2 }, []);
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
    vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) =>
      path === "/agents" && isCeilingRead(options)
        ? new Promise((resolve) => {
            answer = resolve;
          })
        : Promise.resolve({ items: [AGENT], total: 1, categories: [], tags: [], ceiling: null }),
    );
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();

    answer({ items: [AGENT], total: 1, categories: [], tags: [], ceiling: { limit: 5, held: 1 } });
    await waitFor(() => expect(screen.getByRole("button", { name: "New agent" })).toBeEnabled());
  });

  it("keeps the limit while the list reloads", async () => {
    // A filter change reloads the list under a new key; the ceiling is its own
    // query, so the notice and the disabled button do not blink away meanwhile.
    vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) =>
      path === "/agents" && isCeilingRead(options)
        ? Promise.resolve({
            items: [],
            total: 1,
            categories: [],
            tags: [],
            ceiling: { limit: 1, held: 1 },
          })
        : new Promise(() => {}),
    );
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByRole("status")).toHaveTextContent(NOTICE);
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();
  });

  it("shows a caller who cannot create agents neither the notice nor New agent", async () => {
    rig.can = (permission) => permission !== Perm.agentsEdit;
    listing({ limit: 1, held: 1 });
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New agent" })).not.toBeInTheDocument();
    // No ceiling read either: the server would answer null for this caller.
    expect(vi.mocked(apiClient.get).mock.calls.some(([, options]) => isCeilingRead(options))).toBe(
      false,
    );
  });

  it("is unchanged below the limit", async () => {
    listing({ limit: 5, held: 4 });
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    const create = screen.getByRole("button", { name: "New agent" });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("is unchanged when the deployment sets no limit", async () => {
    listing(null);
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "New agent" })).toBeEnabled());
  });
});
