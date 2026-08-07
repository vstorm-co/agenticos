import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminUsersPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { AdminUser } from "@/types";

/**
 * What the deployment's user table draws, against what the API returns.
 *
 * It drew a "Role" column for a field that has not existed since migration
 * `0066` dropped `users.role`: `AdminUserRead` has never carried one, `undefined`
 * renders to nothing, and every row's cell was blank under a translated header -
 * which reads as "nobody has a role set" rather than "this column is not a
 * thing". TypeScript was no help because the hook's own interface asserted the
 * field, and a hand-written type is a claim about the response, not a check on it.
 *
 * The count beside it is the other half: `conversation_count` was computed by a
 * join on every page load, and no column and no interface read it.
 */
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

const USERS: AdminUser[] = [
  {
    id: "u-1",
    email: "kacper@example.com",
    full_name: "Kacper",
    is_active: true,
    is_app_admin: true,
    conversation_count: 12,
    created_at: "2026-07-01T00:00:00Z",
  },
  {
    id: "u-2",
    email: "ada@example.com",
    full_name: null,
    is_active: false,
    is_app_admin: false,
    conversation_count: 0,
    created_at: "2026-07-02T00:00:00Z",
  },
];

/** The query string of the nth list request. */
function requested(nth = 0): string {
  return vi.mocked(apiClient.get).mock.calls[nth]![0] as string;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: USERS, total: USERS.length });
});

describe("the admin users table", () => {
  it("draws no Role column, because the API returns no role", async () => {
    render(<AdminUsersPage />, { wrapper });
    await screen.findByText("kacper@example.com");

    expect(screen.queryByText("Role")).toBeNull();
  });

  it("shows how many conversations each account has", async () => {
    // The join was already being paid for. Rendering it is what makes the cost
    // buy something, and what makes `sort_by=conversations` reachable at all.
    render(<AdminUsersPage />, { wrapper });
    await screen.findByText("kacper@example.com");

    expect(screen.getByRole("button", { name: /conversations/i })).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("asks the server to sort on that count when its header is pressed", async () => {
    render(<AdminUsersPage />, { wrapper });
    await screen.findByText("kacper@example.com");

    await userEvent.click(screen.getByRole("button", { name: /conversations/i }));

    await waitFor(() => {
      expect(requested(vi.mocked(apiClient.get).mock.calls.length - 1)).toContain(
        "sort_by=conversations",
      );
    });
  });

  it("still marks the deployment admin, which is the only authority a row has", async () => {
    // The badge used to live in the Role cell. Deleting the column would
    // otherwise have taken the one true thing on it with the empty one.
    render(<AdminUsersPage />, { wrapper });
    await screen.findByText("kacper@example.com");

    expect(screen.getByText("App")).toBeInTheDocument();
  });
});
