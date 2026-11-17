import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { ConsoleToaster } from "./console-toaster";

beforeEach(() => vi.useFakeTimers());

afterEach(async () => {
  act(() => toast.dismiss());
  await act(async () => vi.runAllTimersAsync());
  cleanup();
  vi.useRealTimers();
});

async function showToast(show: () => void): Promise<void> {
  await act(async () => {
    show();
    await vi.advanceTimersByTimeAsync(0);
  });
}

it("dismisses a clicked notification through its native close control", async () => {
  render(<ConsoleToaster closeLabel="Zamknij" />);
  const dismissed = vi.fn();
  await showToast(() => {
    toast.success("Saved fixture", { onDismiss: dismissed });
  });
  expect(screen.getByRole("button", { name: /^Zamknij$/ })).toBeVisible();
  fireEvent.click(screen.getByText("Saved fixture"));
  expect(screen.getByText("Saved fixture").closest("li")).toHaveAttribute("data-removed", "true");
  expect(dismissed).toHaveBeenCalledTimes(1);
});

it("runs the action before closing and respects an action that prevents dismissal", async () => {
  render(<ConsoleToaster closeLabel="Zamknij" />);
  const action = vi.fn((event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault());
  await showToast(() => {
    toast("Review fixture", { action: { label: "Keep reviewing", onClick: action } });
  });
  fireEvent.click(screen.getByRole("button", { name: "Keep reviewing" }));
  expect(action).toHaveBeenCalledTimes(1);
  expect(screen.getByText("Review fixture").closest("li")).toHaveAttribute("data-removed", "false");
});

it("leaves loading and explicitly non-dismissible notifications visible", async () => {
  render(<ConsoleToaster closeLabel="Zamknij" />);
  await showToast(() => {
    toast.loading("Uploading fixture");
    toast("Persistent fixture", { dismissible: false });
  });
  fireEvent.click(screen.getByText("Uploading fixture"));
  fireEvent.click(screen.getByText("Persistent fixture"));
  expect(screen.getByText("Uploading fixture").closest("li")).toHaveAttribute(
    "data-removed",
    "false",
  );
  expect(screen.getByText("Persistent fixture").closest("li")).toHaveAttribute(
    "data-removed",
    "false",
  );
});
