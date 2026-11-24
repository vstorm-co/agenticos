import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense } from "react";
import { expect, it, vi } from "vitest";

import { ROLE_CATALOG } from "@/test-utils/role-catalog";
import RolesPage from "./page";

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ role: "owner", isAppAdmin: false }),
  useRoleCatalog: () => ({
    isLoading: false,
    catalog: {
      ...ROLE_CATALOG,
      all_permissions: ["agents:view"],
      resource_permissions: ["agents:view"],
    },
  }),
}));
vi.mock("@/components/dashboard/page-header", () => ({ PageHeader: () => null }));

async function renderRoles() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  await act(async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Suspense>
          <RolesPage params={Promise.resolve({ id: "org-1" })} />
        </Suspense>
      </QueryClientProvider>,
    );
  });
}

it("makes the wide permission matrix reachable by keyboard and names its headers", async () => {
  await renderRoles();
  const matrix = await screen.findByRole("region", { name: "Permission matrix" });
  await userEvent.click(screen.getByRole("textbox", { name: "Search permissions…" }));
  await userEvent.tab();
  expect(matrix).toHaveFocus();
  expect(screen.getByRole("columnheader", { name: "Permission" })).toHaveAttribute("scope", "col");
  expect(screen.getByRole("rowheader", { name: /agents:view/ })).toHaveAttribute("scope", "row");
});

it("filters the permission matrix and restores it after clearing an unmatched search", async () => {
  await renderRoles();
  const search = await screen.findByRole("textbox", { name: "Search permissions…" });
  await userEvent.type(search, "not-a-permission");
  expect(screen.queryByRole("rowheader", { name: /agents:view/ })).not.toBeInTheDocument();
  expect(screen.getByText("No permissions match your search")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByRole("rowheader", { name: /agents:view/ })).toBeVisible();
  await userEvent.type(search, "AGENTS");
  expect(screen.getByRole("rowheader", { name: /agents:view/ })).toBeVisible();
});
