import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Agent, AgentCeiling } from "@/types/agents";

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
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));

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

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
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

  it("is unchanged below the limit", async () => {
    listing({ limit: 5, held: 4 });
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New agent" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("is unchanged when the deployment sets no limit", async () => {
    listing(null);
    render(<AgentsPage />, { wrapper });

    expect(await screen.findByText("Support")).toBeInTheDocument();
    expect(screen.queryByText(NOTICE)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New agent" })).toBeEnabled();
  });
});
