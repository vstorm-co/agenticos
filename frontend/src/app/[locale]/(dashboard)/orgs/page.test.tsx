import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import OrgsPage from "./page";

const state = vi.hoisted(() => ({
  fetchOrgs: vi.fn().mockResolvedValue(undefined),
  switchOrg: vi.fn(),
  push: vi.fn(),
  listFailed: false,
  orgs: [
    { id: "personal", name: "Personal", slug: "jordan", is_personal: true },
    { id: "company", name: "Northwind Labs", slug: "northwind", is_personal: false },
  ],
}));
const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
  useSearchParams: () => params,
  usePathname: () => "/orgs",
}));
vi.mock("@/hooks", () => ({
  useOrganizations: () => ({
    ...state,
    activeOrgId: "personal",
  }),
}));
vi.mock("@/components/teams", () => ({ CreateOrgDialog: () => null }));
beforeEach(() => {
  vi.clearAllMocks();
  state.listFailed = false;
});

it("lists both organizations an owner belongs to", async () => {
  render(<OrgsPage />);
  expect(await screen.findByText("2 organizations")).toBeVisible();
  expect(screen.getByRole("link", { name: "Open Personal" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Open Northwind Labs" })).toBeVisible();
});

it("shows a failed load as an error with a retry, never as zero organizations", async () => {
  state.listFailed = true;
  const orgs = state.orgs;
  state.orgs = [];
  render(<OrgsPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Organizations could not be loaded.");
  expect(screen.queryByText("No organizations yet")).toBeNull();
  expect(screen.queryByText("0 organizations")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.fetchOrgs).toHaveBeenCalledTimes(2);
  state.orgs = orgs;
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
  expect(state.fetchOrgs).toHaveBeenCalledOnce();
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
