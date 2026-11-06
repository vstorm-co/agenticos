import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import AccountSettingsPage from "./page";
import { apiClient } from "@/lib/api-client";

vi.mock("@/components/dashboard/active-sessions", () => ({
  ActiveSessions: () => <div>Session list</div>,
}));
vi.mock("@/hooks", () => ({ useAuth: () => ({ user: { id: "u1" }, logout: vi.fn() }) }));
vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { post: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

function fill(next: string, confirmation = next) {
  fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "old-secret" } });
  fireEvent.change(screen.getByLabelText("New password"), { target: { value: next } });
  fireEvent.change(screen.getByLabelText("Confirm new password"), {
    target: { value: confirmation },
  });
}

describe("account security form", () => {
  it("keeps password guidance and session management visible", () => {
    render(<AccountSettingsPage />);
    expect(screen.getByText("Session list")).toBeVisible();
    expect(screen.getByRole("button", { name: "Update password" })).toBeDisabled();
    expect(screen.getByLabelText("Current password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
  });

  it.each([
    ["short", "short"],
    ["new-secret", "different-secret"],
  ])("refuses invalid password pair %s", async (next, confirmation) => {
    render(<AccountSettingsPage />);
    fill(next, confirmation);
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    expect(toast.error).toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("submits its form once and clears the fields only on success", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({});
    const { container } = render(<AccountSettingsPage />);
    fill("new-secret");
    const form = container.querySelector("form");
    if (!form) throw new Error("missing password form");
    fireEvent.submit(form);
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/auth/password/change", {
        current_password: "old-secret",
        new_password: "new-secret",
      }),
    );
    await waitFor(() => expect(screen.getByLabelText("New password")).toHaveValue(""));
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("Confirm new password")).toHaveValue("");
  });

  it("retains the draft after a failed password update", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("offline"));
    render(<AccountSettingsPage />);
    fill("new-secret");
    fireEvent.click(screen.getByRole("button", { name: "Update password" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByLabelText("New password")).toHaveValue("new-secret");
  });
});
