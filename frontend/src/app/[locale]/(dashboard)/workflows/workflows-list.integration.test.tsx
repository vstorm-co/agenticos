import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkflowsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { WorkflowRead } from "@/lib/workflows/types";

/**
 * The workflows list: its status filter, and the permission that hides both
 * creation controls. The create button and per-row duplicate are gated on
 * `workflows:create`, so a caller without it must not see them — not see them and
 * then 403.
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
  usePathname: () => "/workflows",
}));

const perms = vi.hoisted(() => ({ can: (_permission: string): boolean => true }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: perms.can }) }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function workflow(name: string, status: WorkflowRead["status"]): WorkflowRead {
  return {
    id: `${name}-id`,
    slug: name.toLowerCase(),
    name,
    description: null,
    status,
    visibility: "private",
    owner_user_id: "u1",
    current_version_id: status === "published" ? "v1" : null,
    draft_revision: 0,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  };
}

const WORKFLOWS = [
  workflow("Live", "published"),
  workflow("Draft", "draft"),
  workflow("Old", "archived"),
];

/** Serve `rows` from `/workflows` the way the paged route does — a `skip`/`limit` window. */
function serve(rows: WorkflowRead[]) {
  vi.mocked(apiClient.get).mockImplementation((path: string, config?: unknown) => {
    if (path === "/workflows") {
      const params = (config as { params?: { skip?: string; limit?: string } } | undefined)?.params;
      const skip = Number(params?.skip ?? 0);
      const limit = Number(params?.limit ?? 50);
      return Promise.resolve({ items: rows.slice(skip, skip + limit), total: rows.length });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

beforeEach(() => {
  perms.can = () => true;
  vi.mocked(apiClient.get).mockReset();
  serve(WORKFLOWS);
});

describe("the workflows list", () => {
  it("shows every status on 'All'", async () => {
    render(<WorkflowsPage />, { wrapper });

    // The name is a link; the status badge beside it can carry the same word.
    expect(await screen.findByRole("link", { name: "Live" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Draft" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Old" })).toBeInTheDocument();
  });

  it("narrows to one status when one is chosen", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByRole("link", { name: "Live" });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Drafts" }));

    expect(screen.getByRole("link", { name: "Draft" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Live" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Old" })).toBeNull();
  });

  it("offers create and duplicate to a caller who may create", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByText("Live");

    expect(screen.getByRole("button", { name: "New workflow" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Duplicate / })).toHaveLength(WORKFLOWS.length);
  });

  it("hides both creation controls from a caller who may only view", async () => {
    // Grants view (so the list still loads) but not create.
    perms.can = (permission: string) => permission === "workflows:view";
    render(<WorkflowsPage />, { wrapper });
    await screen.findByText("Live");

    expect(screen.queryByRole("button", { name: "New workflow" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Duplicate / })).toBeNull();
  });

  it("does not fetch the list for a caller without workflows:view", async () => {
    perms.can = () => false;
    render(<WorkflowsPage />, { wrapper });

    // The status filter always renders; the list query, gated on view, never runs.
    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "Filter by status" })).toBeInTheDocument(),
    );
    expect(apiClient.get).not.toHaveBeenCalledWith("/workflows");
  });

  it("opens the blank/template dialog from New workflow", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.click(screen.getByRole("button", { name: "New workflow" }));

    expect(await screen.findByText("Blank workflow")).toBeInTheDocument();
    expect(screen.getByText("Two-step sequence")).toBeInTheDocument();
  });
});

describe("the workflows list past one page", () => {
  // Sixty drafts and, last of all, one published workflow — so the published one
  // lands beyond the first page of fifty. This is the exact shape #1787 got
  // wrong: the registry only ever showed the first page, and a status filter over
  // it reported "no matches" for a match that was never on screen.
  const MANY: WorkflowRead[] = [
    ...Array.from({ length: 60 }, (_, i) => workflow(`Draft ${i + 1}`, "draft")),
    workflow("FindMe", "published"),
  ];

  beforeEach(() => serve(MANY));

  it("reaches a workflow on a later page through the pager", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByRole("link", { name: "Draft 1" });

    // The 61st row is not on the first page of fifty.
    expect(screen.queryByRole("link", { name: "FindMe" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByRole("link", { name: "FindMe" })).toBeInTheDocument();
  });

  it("finds a status match that is not on the first page", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByRole("link", { name: "Draft 1" });

    // Filtering to Published surfaces the one match even though it sat past the
    // first page — the false negative Codex flagged, now fixed by filtering the
    // whole walked registry rather than one page of it.
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Published" }));

    expect(await screen.findByRole("link", { name: "FindMe" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Draft 1" })).toBeNull();
  });
});
