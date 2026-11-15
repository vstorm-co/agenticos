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

it("makes the wide permission matrix reachable by keyboard and names its headers", async () => {
  await act(async () => {
    render(
      <Suspense>
        <RolesPage params={Promise.resolve({ id: "org-1" })} />
      </Suspense>,
    );
  });
  const matrix = await screen.findByRole("region", { name: "Permission matrix" });
  await userEvent.tab();
  expect(matrix).toHaveFocus();
  expect(screen.getByRole("columnheader", { name: "Permission" })).toHaveAttribute("scope", "col");
  expect(screen.getByRole("rowheader", { name: /agents:view/ })).toHaveAttribute("scope", "row");
});
