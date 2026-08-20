import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserDetailDrawer } from "./admin/user-detail-drawer";
import { SyncSourceWizard } from "./rag/sync-source-wizard";
import type { AdminUser } from "@/types";

/**
 * Two components that read a row somebody else derives for them.
 *
 * Deriving is right in both cases - it is what stopped the RAG page ending up
 * with nothing selected, and what keeps the admin list the single source of a
 * user's row. What it costs is that the value can move on its own, from a
 * refetch neither component asked for, and both of them treated that as the
 * user having done something.
 *
 * Neither file is in `vitest.config.ts`'s coverage include list, so nothing
 * gates them; these exist because a fix nobody can revert by accident is worth
 * more than the line it occupies.
 */
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function mount(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const CONNECTORS = [
  {
    type: "gdrive",
    name: "Google Drive",
    enabled: true,
    requires: [],
    config_schema: {},
    secret_kind: "gcp_service_account",
  },
];

beforeEach(() => vi.clearAllMocks());

describe("the sync source wizard", () => {
  it("keeps a half-filled form when the collection list reorders underneath it", async () => {
    // `defaultCollection` is derived on the RAG page as `chosen ||
    // collections[0]?.name`, so deleting the oldest collection moves it with
    // nobody touching the wizard. It used to take that as "start again".
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      connectors: CONNECTORS,
      collections: [{ name: "alpha" }, { name: "beta" }],
      orgIntegrations: [],
      onSubmit: vi.fn(),
      onClone: vi.fn(),
      submitting: false,
    };
    const { rerender } = mount(<SyncSourceWizard {...props} defaultCollection="alpha" />);
    await userEvent.type(screen.getByLabelText("Source name"), "Quarterly reports");

    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <SyncSourceWizard {...props} defaultCollection="beta" />
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText("Source name")).toHaveValue("Quarterly reports");
  });
});

describe("the admin user drawer", () => {
  // No cast: the object is the whole of `AdminUser`. It used to need one,
  // because the type claimed a `role` the API has not returned since `0066`.
  const user: AdminUser = {
    id: "u-1",
    email: "kacper@example.com",
    full_name: "Kacper",
    is_active: true,
    is_app_admin: false,
    conversation_count: 3,
    created_at: "2026-07-01T00:00:00Z",
  };

  it("keeps showing the row it was given while the sheet closes", () => {
    // The page holds the id and derives the row, so deleting the user takes it
    // away mid-animation. Returning null then rips the sheet off the screen
    // instead of letting it slide.
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      onUpdate: vi.fn(),
      onDelete: vi.fn(),
      onImpersonate: vi.fn(),
    };
    const { rerender } = mount(<UserDetailDrawer {...props} user={user} />);
    expect(screen.getAllByText("kacper@example.com").length).toBeGreaterThan(0);

    // Deleted: the list no longer has the row. `open` stays true because that
    // is what the component sees while Radix plays the exit animation - jsdom
    // has no animation, so closing it here would unmount the content whatever
    // this component did, and the test would pass against the bug.
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <UserDetailDrawer {...props} user={null} />
      </QueryClientProvider>,
    );

    expect(screen.getAllByText("kacper@example.com").length).toBeGreaterThan(0);
  });
});
