import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ResourceIcon, ResourceIconPicker } from "./resource-icon";

it("keeps marks decorative while a chosen symbol replaces the default", () => {
  const { container, rerender } = render(<ResourceIcon kind="table" />);
  expect(container.querySelector('[data-resource-icon="table"]')).toHaveAttribute(
    "aria-hidden",
    "true",
  );
  rerender(<ResourceIcon kind="workflow" icon="calendar" />);
  expect(container.querySelector('[data-resource-icon="calendar"]')).toBeInTheDocument();
  expect(screen.queryByRole("img")).toBeNull();
});

it("blocks conflicting choices during a write and keeps a refused picker available for retry", async () => {
  const pending = Promise.withResolvers<void>();
  const change = vi
    .fn()
    .mockImplementationOnce(() => pending.promise)
    .mockResolvedValue(undefined);
  render(<ResourceIconPicker kind="table" onChange={change} />);
  await userEvent.click(screen.getByRole("button", { name: "Change icon" }));
  const calendar = screen.getByRole("button", { name: "Calendar" });
  await userEvent.click(calendar);
  expect(calendar).toBeDisabled();
  expect(screen.getByRole("button", { name: "Workflow" })).toBeDisabled();
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await act(async () => pending.reject(new Error("refused")));
  await waitFor(() => expect(calendar).toBeEnabled());
  expect(change).toHaveBeenCalledWith("calendar");
  await userEvent.click(calendar);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(change).toHaveBeenCalledTimes(2);
});
