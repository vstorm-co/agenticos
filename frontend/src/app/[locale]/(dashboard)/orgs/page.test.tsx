import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import OrgsPage from "./page";
import { Perm, type Permission } from "@/types/permissions";

const state = vi.hoisted(() => ({
  fetchOrgs: vi.fn().mockResolvedValue(undefined),
  switchOrg: vi.fn(),
  push: vi.fn(),
  pending: false,
  error: null as Error | null,
  refetch: vi.fn(),
  held: [] as Permission[],
}));
const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
  useSearchParams: () => params,
  usePathname: () => "/orgs",
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (permission: Permission) => state.held.includes(permission) }),
  useOrganizationList: () => ({
    isPending: state.pending,
    error: state.error,
    refetch: state.refetch,
  }),
  useOrganizations: () => ({
    ...state,
    activeOrgId: "personal",
    orgs: [
      { id: "personal", name: "Personal", slug: "jordan", is_personal: true },
      { id: "company", name: "Northwind Labs", slug: "northwind", is_personal: false },
    ],
  }),
}));
vi.mock("@/components/teams", () => ({
  CreateOrgDialog: ({ open, onCreated }: { open: boolean; onCreated: () => void }) =>
    open ? <button onClick={onCreated}>Finish organization creation</button> : null,
}));
beforeEach(() => {
  vi.clearAllMocks();
  state.error = null;
  state.pending = false;
  state.held = [];
});

it("filters memberships by name or slug without requesting other organizations", async () => {
  render(<OrgsPage />);
  await screen.findByRole("link", { name: "Open Personal" });
  const input = screen.getByRole("textbox", { name: "Search organizations…" });
  await userEvent.type(input, " NORTHWIND ");
  expect(screen.getByRole("link", { name: "Open Northwind Labs" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Open Personal" })).toBeNull();
  expect(screen.getByText("1 organization")).toBeVisible();
  await userEvent.clear(input);
  await userEvent.type(input, "jordan");
  expect(screen.getByRole("link", { name: "Open Personal" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "Open Northwind Labs" })).toBeNull();
  expect(state.fetchOrgs).not.toHaveBeenCalled();
});

it("clears an unmatched query without treating memberships as empty", async () => {
  render(<OrgsPage />);
  await screen.findByRole("link", { name: "Open Personal" });
  await userEvent.type(screen.getByRole("textbox"), "unmatched");
  expect(screen.getByText("No results.")).toBeVisible();
  expect(screen.queryByText("No organizations yet")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByRole("link", { name: "Open Personal" })).toBeVisible();
  expect(screen.getByText("2 organizations")).toBeVisible();
});

it("retains switching for a filtered organization", async () => {
  render(<OrgsPage />);
  await screen.findByRole("link", { name: "Open Personal" });
  await userEvent.type(screen.getByRole("textbox"), "Northwind");
  await userEvent.click(screen.getByRole("button", { name: "Switch" }));
  expect(state.switchOrg).toHaveBeenCalledWith("company");
  expect(state.push).toHaveBeenCalledWith("/dashboard");
});

it("distinguishes a failed membership read from an empty organization list and offers retry", async () => {
  state.error = new Error("Unavailable");
  render(<OrgsPage />);
  expect(screen.queryByText("No organizations yet")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Open Personal" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});
it("keeps the workspace grid loading until memberships resolve", () => {
  state.pending = true;
  render(<OrgsPage />);
  expect(screen.queryByText("No organizations yet")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Open Personal" })).not.toBeInTheDocument();
});

it("refreshes memberships after the create dialog reports a new organization", async () => {
  render(<OrgsPage />);
  await userEvent.click(screen.getByRole("button", { name: "New organization" }));
  await userEvent.click(screen.getByRole("button", { name: "Finish organization creation" }));
  expect(state.refetch).toHaveBeenCalledOnce();
});

it("keeps organization switch actions aligned without workspace settings shortcuts", () => {
  state.held = [Perm.orgSettings, Perm.approvalsDecide];
  render(<OrgsPage />);
  expect(screen.queryByText("Settings for this workspace")).toBeNull();
  expect(screen.queryByRole("link", { name: "AI & services" })).toBeNull();
  expect(screen.queryByRole("link", { name: "Budget and approvals" })).toBeNull();
  expect(screen.getByRole("button", { name: "Current" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Switch" })).toBeEnabled();
});
