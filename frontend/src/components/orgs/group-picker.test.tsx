import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { GroupPicker } from "./group-picker";

const state = vi.hoisted(() => ({
  groups: [{ id: "finance", name: "Finance" }],
  error: null as Error | null,
  isLoading: false,
}));
vi.mock("@/hooks/use-groups", () => ({ useGroups: () => state }));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "org" }),
}));
beforeEach(() => {
  state.groups = [{ id: "finance", name: "Finance" }];
  state.error = null;
  state.isLoading = false;
});

it("keeps a deleted selected group removable instead of silently opening the audience", async () => {
  const change = vi.fn();
  render(<GroupPicker selected={["deleted"]} onChange={change} />);
  await userEvent.click(screen.getByRole("checkbox", { name: "Finance" }));
  expect(change).toHaveBeenLastCalledWith(["deleted", "finance"]);
  await userEvent.click(screen.getByRole("checkbox", { name: "deleted" }));
  expect(change).toHaveBeenLastCalledWith([]);
});

it("distinguishes failures from an empty organization and respects disabled controls", () => {
  state.error = new Error("offline");
  const { rerender } = render(<GroupPicker selected={["deleted"]} onChange={vi.fn()} disabled />);
  expect(
    screen.getByText("Groups could not be loaded. Existing selections are kept."),
  ).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "deleted" })).toBeDisabled();
  state.error = null;
  state.groups = [];
  state.isLoading = true;
  rerender(<GroupPicker selected={[]} onChange={vi.fn()} />);
  expect(screen.getByText("Loading groups…")).toBeVisible();
  state.isLoading = false;
  rerender(<GroupPicker selected={[]} onChange={vi.fn()} />);
  expect(screen.getByText("No groups in this organization.")).toBeVisible();
});
