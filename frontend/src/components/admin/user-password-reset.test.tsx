import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { AdminUser } from "@/types";
import { UserPasswordReset } from "./user-password-reset";

vi.mock("@/lib/api-client", () => ({ apiClient: { post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const account: AdminUser = {
  id: "fixture-user",
  email: "user@example.test",
  full_name: null,
  is_active: true,
  is_app_admin: false,
  conversation_count: 0,
  created_at: "2026-11-01T00:00:00Z",
};

it("copies the recovery link and keeps it available for manual copy", async () => {
  const user = userEvent.setup();
  const url = "https://console.example.test/reset-password?token=fixture";
  vi.mocked(apiClient.post).mockResolvedValueOnce({ reset_url: url });
  render(<UserPasswordReset user={account} onClose={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: "Copy reset link" }));

  expect(apiClient.post).toHaveBeenCalledWith("/admin/users/fixture-user/password-reset", {
    delivery: "link",
  });
  expect(await screen.findByRole("textbox", { name: "Password reset link" })).toHaveValue(url);
  await waitFor(async () => expect(await navigator.clipboard.readText()).toBe(url));
});

it("offers link recovery after a failed email attempt", async () => {
  const user = userEvent.setup();
  const onClose = vi.fn();
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("mail unavailable"));
  render(<UserPasswordReset user={account} onClose={onClose} />);

  await user.click(screen.getByRole("button", { name: "Send reset email" }));

  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy reset link" })).toBeEnabled();
  expect(onClose).not.toHaveBeenCalled();
});
