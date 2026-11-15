import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { ConsoleToaster } from "./console-toaster";

afterEach(() => {
  act(() => {
    toast.dismiss();
  });
});

it("dismisses a clicked notification through its native close control", async () => {
  render(<ConsoleToaster />);
  const dismissed = vi.fn();
  act(() => {
    toast.success("Saved fixture", { onDismiss: dismissed });
  });
  fireEvent.click(await screen.findByText("Saved fixture"));
  await waitFor(() =>
    expect(screen.getByText("Saved fixture").closest("li")).toHaveAttribute("data-removed", "true"),
  );
  expect(dismissed).toHaveBeenCalledTimes(1);
});

it("runs the action before closing and respects an action that prevents dismissal", async () => {
  render(<ConsoleToaster />);
  const action = vi.fn((event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault());
  act(() => {
    toast("Review fixture", { action: { label: "Keep reviewing", onClick: action } });
  });
  fireEvent.click(await screen.findByRole("button", { name: "Keep reviewing" }));
  expect(action).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Review fixture").closest("li")).toHaveAttribute("data-removed", "false");
});

it("leaves loading and explicitly non-dismissible notifications visible", async () => {
  render(<ConsoleToaster />);
  act(() => {
    toast.loading("Uploading fixture");
    toast("Persistent fixture", { dismissible: false });
  });
  fireEvent.click(await screen.findByText("Uploading fixture"));
  fireEvent.click(await screen.findByText("Persistent fixture"));
  expect(screen.getByText("Uploading fixture").closest("li")).toHaveAttribute(
    "data-removed",
    "false",
  );
  expect(screen.getByText("Persistent fixture").closest("li")).toHaveAttribute(
    "data-removed",
    "false",
  );
});
