import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ColumnDefaultField } from "./column-default-field";
it("clears a typed column default without changing the column type", async () => {
  const change = vi.fn();
  render(
    <ColumnDefaultField
      id="name"
      column={{ label: "Name", type: "text", nullable: true, default: "New item" }}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Clear default" }));
  expect(change).toHaveBeenCalledWith(null);
});
