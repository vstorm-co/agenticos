import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { GroupMemberAdd } from "./group-member-add";
import type { OrganizationMember } from "@/types";

const person: OrganizationMember = {
  id: "m1",
  organization_id: "o1",
  user_id: "u1",
  role: "member",
  email: "ann@example.test",
  full_name: "Ann",
  avatar_url: null,
  avatar_color: null,
  joined_at: "2026-11-01T00:00:00Z",
  source: "manual",
};
it("keeps the chosen person until the add succeeds, including after a refused attempt", async () => {
  const add = vi.fn<(id: string, onAdded: () => void) => void>();
  const view = render(<GroupMemberAdd candidates={[person]} pending={false} onAdd={add} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Ann (ann@example.test)" }));
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(add).toHaveBeenCalledWith("u1", expect.any(Function));
  view.rerender(<GroupMemberAdd candidates={[person]} pending onAdd={add} />);
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(screen.getByRole("combobox")).toHaveTextContent("Ann");
  view.rerender(<GroupMemberAdd candidates={[person]} pending={false} onAdd={add} />);
  expect(screen.getByRole("combobox")).toHaveTextContent("Ann");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  const done = add.mock.lastCall?.[1];
  if (!done) throw new Error("No completion callback");
  act(() => done());
  expect(screen.getByRole("combobox")).not.toHaveTextContent("Ann");
});

it("explains a complete group without offering an unusable add form", () => {
  render(<GroupMemberAdd candidates={[]} pending={false} onAdd={vi.fn()} />);
  expect(screen.getByText("Everyone is already in this group")).toBeVisible();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Add" })).toBeNull();
});
