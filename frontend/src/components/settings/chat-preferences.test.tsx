import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

import { ChatPreferences } from "./chat-preferences";

const { toastError } = vi.hoisted(() => ({ toastError: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: toastError } }));

const user = { id: "u1", email: "a@example.com", queue_while_working: false } as User;

describe("choosing what a message sent mid-run does (#2087)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    toastError.mockReset();
    useAuthStore.setState({ user });
  });

  it("renders nothing without a signed-in person", () => {
    useAuthStore.setState({ user: null });
    const { container } = render(<ChatPreferences />);
    expect(container).toBeEmptyDOMElement();
  });

  it("saves the choice on the account and shows what came back", async () => {
    const patch = vi
      .spyOn(apiClient, "patch")
      .mockResolvedValue({ ...user, queue_while_working: true });
    render(<ChatPreferences />);

    const toggle = screen.getByRole("switch", { name: "Queue messages while the agent works" });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);

    await waitFor(() => expect(toggle).toBeChecked());
    expect(patch).toHaveBeenCalledWith("/users/me", { queue_while_working: true });
  });

  it("says why a refused save did not take, and keeps the old choice", async () => {
    vi.spyOn(apiClient, "patch").mockRejectedValueOnce(new ApiError(400, "Nope"));
    render(<ChatPreferences />);

    const toggle = screen.getByRole("switch", { name: "Queue messages while the agent works" });
    fireEvent.click(toggle);

    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(toggle).not.toBeChecked();
  });

  it("falls back to its own sentence for a failure that is not the API's", async () => {
    vi.spyOn(apiClient, "patch").mockRejectedValueOnce(new Error("offline"));
    render(<ChatPreferences />);

    fireEvent.click(screen.getByRole("switch", { name: "Queue messages while the agent works" }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Failed to save preference"));
  });
});
