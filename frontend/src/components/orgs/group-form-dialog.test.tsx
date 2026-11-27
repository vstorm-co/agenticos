import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { GroupFormDialog } from "./group-form-dialog";
import type { Group } from "@/types/groups";

const state = vi.hoisted(() => ({
  tenant: "org",
  budget: false,
  create: vi.fn(),
  update: vi.fn(),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => state.tenant }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => state.budget }) }));
vi.mock("@/hooks", () => ({
  useGroups: () => ({
    create: { mutateAsync: state.create },
    update: { mutateAsync: state.update },
  }),
}));
vi.mock("@/components/money/currency-organization-switch", () => ({
  CurrencyOrganizationSwitch: () => <p>Switch organization</p>,
}));
const group: Group = {
  id: "group",
  organization_id: "org",
  name: "Research",
  description: null,
  icon: null,
  monthly_budget_usd: "25",
  created_at: "2026-11-01T00:00:00Z",
  member_count: 1,
};
beforeEach(() => {
  state.tenant = "org";
  state.budget = false;
  state.create.mockReset();
  state.update.mockReset();
});
it("never edits a different organization with the active organization's quote", () => {
  state.tenant = "another";
  render(<GroupFormDialog orgId="org" group={group} onClose={vi.fn()} />);
  expect(screen.getByText("Switch organization")).toBeVisible();
  expect(screen.queryByLabelText("Name")).toBeNull();
});
it("a rename without budget authority preserves the existing original limit terms", async () => {
  render(<GroupFormDialog orgId="org" group={group} onClose={vi.fn()} />);
  const input = screen.getByLabelText("Name");
  await userEvent.clear(input);
  await userEvent.type(input, "Research team");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(state.update).toHaveBeenCalledWith({
    groupId: "group",
    input: {
      name: "Research team",
      description: null,
      icon: null,
      monetary_inputs: {},
    },
  });
});
