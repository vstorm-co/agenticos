import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UserDetailDrawer } from "./user-detail-drawer";
import { apiClient } from "@/lib/api-client";
import type { AdminUser } from "@/types";

/**
 * The one screen where a deployment admin decides something about a person.
 *
 * It used to show four facts - the id, the email, the name already in the table
 * and a join date - and none of them answered the question being asked (#942).
 * What is pinned here is that each new block says which of three things
 * happened: reading, read, or could not be read. An admin acting on "in no
 * organizations" when the truth was "the request failed" is acting on nothing.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const USER: AdminUser = {
  id: "u-1",
  email: "ada@example.com",
  full_name: "Ada Lovelace",
  is_active: true,
  is_app_admin: false,
  conversation_count: 3,
  created_at: "2026-07-01T00:00:00Z",
};

const DETAIL = {
  memberships: [
    {
      organization_id: "o-1",
      name: "Acme",
      slug: "acme",
      is_personal: false,
      role: "builder",
    },
  ],
  last_seen_at: "2026-08-20T09:00:00Z",
  active_sessions: 2,
  newest_session_at: "2026-08-19T09:00:00Z",
};

function serve(detail: unknown = DETAIL, conversations: unknown[] = []) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/detail")) {
      if (detail instanceof Error) throw detail;
      return detail;
    }
    return { items: conversations };
  });
}

function mount(user: AdminUser = USER) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <UserDetailDrawer
      user={user}
      open
      onOpenChange={vi.fn()}
      onUpdate={update}
      onDelete={vi.fn()}
      onImpersonate={vi.fn()}
    />,
    { wrapper },
  );
}

const update = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

describe("what the drawer answers", () => {
  it("names each organization and the role in it", async () => {
    // The answer it exists to give, and the one entirely absent before.
    mount();

    const membership = await screen.findByText("Acme");
    expect(membership.closest("li")).toHaveTextContent("builder");
  });

  it("does not link a row an admin cannot open", async () => {
    // `/orgs/{id}` resolves through `get_for_user`, which 404s for anybody who
    // is not a member - an app admin included, and the target's own personal
    // organization is the common case. A link most of these rows cannot open
    // is worse than the name and the role (#1245).
    mount();

    await screen.findByText("Acme");
    expect(screen.queryByRole("link", { name: /Acme/ })).toBeNull();
  });

  it("does not claim a sign-in history the request failed to fetch", async () => {
    // "Never signed in" is a claim about the account, and the read that would
    // have supported it did not answer.
    serve(new Error("Backend unavailable"));
    mount();

    await waitFor(() => expect(screen.getAllByText("Backend unavailable")).toHaveLength(2));
    expect(screen.queryByText("Never signed in")).toBeNull();
  });

  it("says an account has never signed in rather than leaving it blank", async () => {
    // Not the same as dormant, and it is the field an admin looks for first.
    serve({ ...DETAIL, last_seen_at: null, active_sessions: 0, newest_session_at: null });
    mount();

    expect(await screen.findByText("Never signed in")).toBeVisible();
    expect(screen.getByText(/No sessions open/)).toBeVisible();
  });

  it("keeps a failed read and an empty one apart", async () => {
    // The distinction the whole block exists for. A refusal shows what was
    // refused; "in no organizations" is a fact, and an admin acting on it when
    // the request had failed is acting on nothing.
    serve(new Error("Backend unavailable"));
    mount();

    await waitFor(() => expect(screen.getAllByText("Backend unavailable")).toHaveLength(2));
    expect(screen.queryByText("In no organizations.")).toBeNull();
    expect(screen.queryByText(/sessions open/)).toBeNull();
  });

  it("says so when the person really is in no organization", async () => {
    serve({ ...DETAIL, memberships: [] });
    mount();

    expect(await screen.findByText("In no organizations.")).toBeVisible();
  });
});

describe("the three privileged actions", () => {
  it("asks before suspending, and names what happens", async () => {
    mount();
    await screen.findByText("Acme");

    await userEvent.click(screen.getByRole("button", { name: /Suspend/ }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/signed out immediately/)).toBeVisible();
    expect(update).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("u-1", { is_active: false }));
  });

  it("asks before granting deployment administration", async () => {
    mount();
    await screen.findByText("Acme");

    await userEvent.click(screen.getByRole("button", { name: /Promote|admin/i }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/every permission in every organization/)).toBeVisible();
  });

  it("does not ask before reactivating, which gives access back", async () => {
    // The recoverable direction. A confirmation on the button that undoes one
    // is a question about nothing.
    mount({ ...USER, is_active: false });
    await screen.findByText("Acme");

    await userEvent.click(screen.getByRole("button", { name: /Reactivate/i }));

    await waitFor(() => expect(update).toHaveBeenCalledWith("u-1", { is_active: true }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });
});
