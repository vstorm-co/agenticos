import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import DatasetsPage from "./page";

/**
 * Who is offered which control on `/datasets`.
 *
 * A dataset's cases are often copied out of real conversations, so the page
 * itself is gated on `datasets:view`, and creating one on `datasets:edit`. A
 * control the caller may not use is not drawn - a Viewer sees the datasets
 * shared with them and no button that would answer 403.
 */

const { get, granted } = vi.hoisted(() => ({ get: vi.fn(), granted: { perms: [] as string[] } }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (perm: string) => granted.perms.includes(perm),
    isLoading: false,
  }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SHARED = {
  id: "d1",
  name: "refunds",
  description: null,
  visibility: "org",
  owner_user_id: "someone",
  latest_version: 2,
  case_count: 4,
  can_edit: false,
  created_at: "2026-10-13T00:00:00Z",
  updated_at: null,
};

describe("the datasets page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({ items: [SHARED], total: 1 });
  });

  it("shows a Viewer what was shared with them and no control to change it", async () => {
    granted.perms = [Perm.datasetsView];
    render(<DatasetsPage />, { wrapper });

    expect(await screen.findByText("refunds")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New dataset" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete refunds" })).toBeNull();
  });

  it("tells a Viewer with nothing shared to ask an owner, not to create one", async () => {
    granted.perms = [Perm.datasetsView];
    get.mockResolvedValue({ items: [], total: 0 });
    render(<DatasetsPage />, { wrapper });

    expect(await screen.findByText("Nothing has been shared with you yet")).toBeInTheDocument();
    expect(screen.queryByText("No datasets yet")).toBeNull();
  });

  it("offers somebody who may create datasets the first one when there are none", async () => {
    granted.perms = [Perm.datasetsView, Perm.datasetsEdit];
    get.mockResolvedValue({ items: [], total: 0 });
    render(<DatasetsPage />, { wrapper });

    expect(await screen.findByText("No datasets yet")).toBeInTheDocument();
  });

  it("offers a member who may edit datasets the create button", async () => {
    granted.perms = [Perm.datasetsView, Perm.datasetsEdit];
    render(<DatasetsPage />, { wrapper });
    expect(await screen.findByRole("button", { name: "New dataset" })).toBeInTheDocument();
  });

  it("shows the locked state without datasets:view", () => {
    granted.perms = [];
    render(<DatasetsPage />, { wrapper });
    expect(screen.getByText("You cannot see this organization's datasets")).toBeInTheDocument();
  });
});
