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
// A page of five, not fifty: crossing a page boundary is the behaviour under
// test, and fifty full cards per render ran past the timeout on a loaded CI runner.
const TEST_PAGE = 5;
vi.mock("@/components/ui/list-controls", async () => {
  const actual = await vi.importActual<typeof import("@/components/ui/list-controls")>(
    "@/components/ui/list-controls",
  );
  return {
    ...actual,
    useListControls: <T,>(args: Parameters<typeof actual.useListControls<T>>[0]) =>
      actual.useListControls<T>({ ...args, pageSize: TEST_PAGE }),
  };
});
let params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/workflows",
  useSearchParams: () => params,
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
    live_trigger: null,
    tags: [],
    trigger_active: null,
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
  params = new URLSearchParams();
  window.history.replaceState({}, "", "/workflows");
  perms.can = () => true;
  vi.mocked(apiClient.get).mockReset();
  serve(WORKFLOWS);
});

describe("the workflows list", () => {
  it("shows every status on 'All'", async () => {
    render(<WorkflowsPage />, { wrapper });

    // The name is a link; the status badge beside it can carry the same word.
    expect(await screen.findByRole("link", { name: "Open Live" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Draft" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Old" })).toBeInTheDocument();
  });

  it("narrows to one status when one is chosen", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByRole("link", { name: "Open Live" });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Drafts" }));

    expect(screen.getByRole("link", { name: "Open Draft" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Live" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Open Old" })).toBeNull();
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

  it("opens the start/template dialog from New workflow", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByText("Live");

    await userEvent.click(screen.getByRole("button", { name: "New workflow" }));

    expect(await screen.findByText("How does it start?")).toBeInTheDocument();
    expect(screen.getByText("Two-step sequence")).toBeInTheDocument();
  });
});

describe("the workflows list past one page", () => {
  // A page of drafts and, last of all, one published workflow — so the published
  // one lands beyond the first page. This is the exact shape #1787 got wrong: the
  // registry only ever showed the first page, and a status filter over it
  // reported "no matches" for a match that was never on screen.
  const MANY: WorkflowRead[] = [
    ...Array.from({ length: TEST_PAGE + 1 }, (_, i) => workflow(`Draft ${i + 1}`, "draft")),
    workflow("FindMe", "published"),
  ];

  beforeEach(() => serve(MANY));

  it("reaches a workflow on a later page through the pager", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByRole("link", { name: "Open Draft 1" });

    // The last row is not on the first page.
    expect(screen.queryByRole("link", { name: "Open FindMe" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(await screen.findByRole("link", { name: "Open FindMe" })).toBeInTheDocument();
  });

  it("finds a status match that is not on the first page", async () => {
    render(<WorkflowsPage />, { wrapper });
    await screen.findByRole("link", { name: "Open Draft 1" });

    // Filtering to Published surfaces the one match even though it sat past the
    // first page — the false negative Codex flagged, now fixed by filtering the
    // whole walked registry rather than one page of it.
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Published" }));

    expect(await screen.findByRole("link", { name: "Open FindMe" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open Draft 1" })).toBeNull();
  });

  describe("finding one", () => {
    const tagged = (name: string, tags: string[], updated: string, created: string) => ({
      ...workflow(name, "published"),
      tags,
      updated_at: updated,
      created_at: created,
      description: `${name} automation`,
    });
    const ROWS = [
      tagged("Beta", ["sales"], "2026-09-03T00:00:00Z", "2026-01-01T00:00:00Z"),
      tagged("Alpha", ["ops"], "2026-09-01T00:00:00Z", "2026-03-01T00:00:00Z"),
      tagged("Gamma", ["sales", "nightly"], "2026-09-02T00:00:00Z", "2026-02-01T00:00:00Z"),
    ];
    const order = () =>
      screen
        .getAllByRole("link", { name: /^Open / })
        .map((link) => link.getAttribute("aria-label"));

    it("searches by name, description or tag, starting from the URL", async () => {
      serve(ROWS);
      params = new URLSearchParams("q=night");
      render(<WorkflowsPage />, { wrapper });

      expect(await screen.findByRole("link", { name: "Open Gamma" })).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Open Beta" })).toBeNull();

      await userEvent.clear(screen.getByPlaceholderText("Search workflows"));
      await userEvent.type(screen.getByPlaceholderText("Search workflows"), "alpha auto");
      expect(order()).toEqual(["Open Alpha"]);
      expect(new URL(window.location.href).searchParams.get("q")).toBe("alpha auto");
    });

    it("sorts by last edit, by name or by the newest", async () => {
      serve(ROWS);
      render(<WorkflowsPage />, { wrapper });
      await screen.findByRole("link", { name: "Open Beta" });
      expect(order()).toEqual(["Open Beta", "Open Gamma", "Open Alpha"]);

      await userEvent.click(screen.getByRole("combobox", { name: "Sort workflows" }));
      await userEvent.click(screen.getByRole("option", { name: "Name" }));
      expect(order()).toEqual(["Open Alpha", "Open Beta", "Open Gamma"]);

      await userEvent.click(screen.getByRole("combobox", { name: "Sort workflows" }));
      await userEvent.click(screen.getByRole("option", { name: "Newest" }));
      expect(order()).toEqual(["Open Alpha", "Open Gamma", "Open Beta"]);
      expect(new URL(window.location.href).searchParams.get("sort")).toBe("created");

      await userEvent.click(screen.getByRole("combobox", { name: "Sort workflows" }));
      await userEvent.click(screen.getByRole("option", { name: "Last edited" }));
      expect(new URL(window.location.href).searchParams.get("sort")).toBeNull();
    });

    it("narrows to a tag, and clears every filter from the empty state", async () => {
      serve(ROWS);
      params = new URLSearchParams("status=draft");
      render(<WorkflowsPage />, { wrapper });
      await userEvent.click(await screen.findByRole("button", { name: "Clear filter" }));
      await screen.findByRole("link", { name: "Open Beta" });

      await userEvent.click(screen.getByRole("combobox", { name: "Filter by tag" }));
      await userEvent.click(screen.getByRole("option", { name: "sales" }));
      expect(order()).toEqual(["Open Beta", "Open Gamma"]);

      await userEvent.click(screen.getByRole("combobox", { name: "Filter by tag" }));
      await userEvent.click(screen.getByRole("option", { name: "All tags" }));
      expect(order()).toHaveLength(3);
    });

    it("offers no tag filter where no workflow is tagged", async () => {
      serve(WORKFLOWS);
      render(<WorkflowsPage />, { wrapper });
      await screen.findByRole("link", { name: "Open Live" });
      expect(screen.queryByRole("combobox", { name: "Filter by tag" })).toBeNull();
    });
  });

  describe("looking after one", () => {
    it("archives, restores and deletes from a card's menu", async () => {
      serve(WORKFLOWS);
      vi.mocked(apiClient.post).mockResolvedValue({
        ...workflow("Live", "archived"),
        can_edit: false,
        draft_graph: null,
      });
      vi.mocked(apiClient.delete).mockResolvedValue(undefined);
      render(<WorkflowsPage />, { wrapper });
      await screen.findByRole("link", { name: "Open Live" });

      await userEvent.click(screen.getByRole("button", { name: "More for Live" }));
      await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));
      await waitFor(() =>
        expect(apiClient.post).toHaveBeenCalledWith("/workflows/Live-id/archive"),
      );

      await userEvent.click(screen.getByRole("button", { name: "More for Old" }));
      await userEvent.click(screen.getByRole("menuitem", { name: "Restore" }));
      await waitFor(() =>
        expect(apiClient.post).toHaveBeenCalledWith("/workflows/Old-id/unarchive"),
      );

      await userEvent.click(screen.getByRole("button", { name: "More for Old" }));
      await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      await userEvent.click(screen.getByRole("button", { name: "Delete" }));
      await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/workflows/Old-id"));
    });

    it("hides the menu from a member whose role does not edit workflows", async () => {
      serve(WORKFLOWS);
      perms.can = (permission) => permission !== "workflows:edit";
      render(<WorkflowsPage />, { wrapper });
      await screen.findByRole("link", { name: "Open Live" });
      expect(screen.queryByRole("button", { name: "More for Live" })).toBeNull();
    });
  });
});
