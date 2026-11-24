import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SkillsPage from "./page";
import type { SkillSection, SkillSummary } from "@/types/providers";

/**
 * Arranging the Skills page.
 *
 * By agent unless the address says otherwise, the choice kept in the address,
 * the plain paged grid one pick away, and the search narrowing the sections
 * the server arranges rather than a page the browser happens to hold.
 */

const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));
vi.mock("@/components/agents/add-to-agent", () => ({ AddToAgent: () => null }));
vi.mock("@/components/skills/proposed-changes", () => ({ ProposedChanges: () => null }));
vi.mock("@/components/skills/skill-gallery-dialog", () => ({ SkillGalleryDialog: () => null }));
vi.mock("@/components/skills/create-skill-dialog", () => ({ CreateSkillDialog: () => null }));

function skill(name: string, overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    id: `id-${name}`,
    name,
    description: `What ${name} is for.`,
    category: null,
    visibility: "org",
    file_count: 0,
    built_in: false,
    excerpt: "",
    ...overrides,
  };
}

const REFUNDS = skill("refunds");
const BY: Record<string, SkillSection[]> = {
  agent: [
    {
      key: "agent:a2",
      kind: "agent",
      count: 1,
      agent: { id: "a2", name: "Billing", slug: "billing" },
      items: [REFUNDS],
    },
    {
      key: "agent:a1",
      kind: "agent",
      count: 2,
      agent: { id: "a1", name: "Support desk", slug: "support-desk" },
      items: [REFUNDS, skill("tone")],
    },
    { key: "unused", kind: "unused", count: 1, items: [skill("lonely")] },
  ],
  origin: [
    { key: "origin:org", kind: "org", count: 2, items: [REFUNDS, skill("tone")] },
    {
      key: "origin:gallery:finance",
      kind: "gallery",
      industry: "finance",
      count: 1,
      items: [skill("ledger-close", { built_in: true, gallery_industry: "finance" })],
    },
  ],
};

function answer(url: string) {
  const path = new URL(url, "http://test");
  if (path.pathname === "/skills/sections") {
    const arrange = path.searchParams.get("arrange") ?? "agent";
    return Promise.resolve({
      arrange,
      sections: BY[arrange] ?? [],
      total: 3,
      categories: [],
      suggested_categories: [],
    });
  }
  if (path.pathname === "/skills") {
    return Promise.resolve({
      items: [REFUNDS, skill("tone"), skill("lonely")],
      total: 3,
      categories: [],
      suggested_categories: [],
    });
  }
  return Promise.resolve({ items: [], total: 0 });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function requested(prefix: string): string[] {
  return get.mock.calls.map(([url]) => String(url)).filter((url) => url.startsWith(prefix));
}

async function arrangeBy(current: string, next: string) {
  await userEvent.click(screen.getByRole("button", { name: current }));
  await userEvent.click(screen.getByRole("menuitemradio", { name: next }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", "/skills");
  get.mockImplementation(answer);
});

describe("arranging the skills page", () => {
  it("arranges by agent by default, a shared skill under each of its agents", async () => {
    render(<SkillsPage />, { wrapper });

    expect(await screen.findByText("Support desk")).toBeInTheDocument();
    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.getByText("Not used by an agent you can see")).toBeInTheDocument();
    expect(screen.getAllByText("refunds")).toHaveLength(2);
    expect(requested("/skills/sections")).toContain("/skills/sections?arrange=agent&sort=name");
    expect(requested("/skills?")).toEqual([]);
  });

  it("shows the plain paged grid when picked, and keeps the pick in the address", async () => {
    render(<SkillsPage />, { wrapper });
    await screen.findByText("Support desk");

    await arrangeBy("By agent", "No sections");

    expect(await screen.findByText("lonely")).toBeInTheDocument();
    expect(screen.queryByText("Support desk")).not.toBeInTheDocument();
    expect(requested("/skills?")).toContain("/skills?sort=name&skip=0&limit=50");
    expect(window.location.search).toBe("?arrange=none");

    await arrangeBy("No sections", "By agent");
    expect(await screen.findByText("Support desk")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("splits shipped skills by gallery industry when arranged by origin", async () => {
    render(<SkillsPage />, { wrapper });
    await screen.findByText("Support desk");

    await arrangeBy("By agent", "By origin");

    expect(await screen.findByText("Built-in · Finance and insurance")).toBeInTheDocument();
    expect(screen.getByText("Organization")).toBeInTheDocument();
    expect(window.location.search).toBe("?arrange=origin");
  });

  it("narrows the arranged sections with the search, on the server", async () => {
    render(<SkillsPage />, { wrapper });
    await screen.findByText("Support desk");

    await userEvent.type(screen.getByPlaceholderText("Search skills…"), "refund");

    await waitFor(() =>
      expect(requested("/skills/sections")).toContain(
        "/skills/sections?arrange=agent&sort=name&q=refund",
      ),
    );
  });

  it("says there is nothing yet when no section holds a skill", async () => {
    get.mockImplementation((url: string) =>
      url.startsWith("/skills/sections")
        ? Promise.resolve({ arrange: "agent", sections: [], total: 0, categories: [] })
        : answer(url),
    );
    render(<SkillsPage />, { wrapper });

    expect(await screen.findByText("No skills yet")).toBeInTheDocument();
  });
});
