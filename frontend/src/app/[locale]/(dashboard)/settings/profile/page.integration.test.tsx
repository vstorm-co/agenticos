import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import { ProfileIdentitySettings } from "@/components/settings/profile-identity-settings";
import ProfileSettingsPage from "./page";

vi.mock("@/hooks", () => ({ useAuth: () => ({ user: useAuthStore((state) => state.user) }) }));
vi.mock("@/lib/api-client", () => ({ apiClient: { patch: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock("@/components/dashboard/active-sessions", () => ({ ActiveSessions: () => null }));
vi.mock("@/components/settings/agent-context-settings", () => ({
  AgentContextSettings: () => null,
}));
vi.mock("@/components/settings/appearance-settings", () => ({ AppearanceSettings: () => null }));
vi.mock("@/components/settings/coding-accounts", () => ({ CodingAccounts: () => null }));
vi.mock("@/components/settings/chat-accounts", () => ({ ChatAccounts: () => null }));
vi.mock("@/components/memory/forget-me", () => ({ ForgetMe: () => null }));

const USER: User = {
  id: "u1",
  email: "member@example.com",
  full_name: "Jamie",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};
beforeEach(() => {
  vi.mocked(apiClient.patch).mockReset();
  useAuthStore.setState({ user: USER });
});

it("offers saving only when the profile differs from the stored values", async () => {
  render(<ProfileSettingsPage />);
  const save = screen.getByRole("button", { name: "Save changes" });
  expect(save).toBeDisabled();
  await userEvent.type(screen.getByRole("textbox", { name: "Display name" }), " edited");
  expect(save).toBeEnabled();
  await userEvent.clear(screen.getByRole("textbox", { name: "Display name" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Display name" }), "Jamie");
  expect(save).toBeDisabled();
  expect(apiClient.patch).not.toHaveBeenCalled();
});

it("saves the changed name and settles back to an unchanged profile", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ ...USER, full_name: "Jamie edited" });
  render(<ProfileSettingsPage />);
  await userEvent.type(screen.getByRole("textbox", { name: "Display name" }), " edited");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(apiClient.patch).toHaveBeenCalledWith("/users/me", { full_name: "Jamie edited" });
  await waitFor(() => expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled());
});

it("keeps the confirmed email after staging a new address and prevents sending it again", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ ...USER, pending_email: "new@example.com" });
  render(<ProfileSettingsPage />);
  await userEvent.clear(screen.getByRole("textbox", { name: "Email" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Email" }), "new@example.com");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(screen.getByRole("textbox", { name: "Email" })).toHaveValue(USER.email),
  );
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  expect(apiClient.patch).toHaveBeenCalledWith("/users/me", { email: "new@example.com" });
  expect(screen.getByText(/new@example.com/)).toBeVisible();
});

it("preserves the edited value when saving fails", async () => {
  vi.mocked(apiClient.patch).mockRejectedValue(new Error("offline"));
  render(<ProfileSettingsPage />);
  await userEvent.type(screen.getByRole("textbox", { name: "Display name" }), " edited");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled());
  expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("Jamie edited");
});

it("saves the guided identity before moving to the next question", async () => {
  const next = vi.fn();
  vi.mocked(apiClient.patch)
    .mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce({ ...USER, full_name: "Jamie edited" });
  render(<ProfileIdentitySettings section="identity" onContinue={next} saveLabel="Continue" />);
  await userEvent.type(screen.getByRole("textbox", { name: "Display name" }), " edited");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
  expect(next).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "Display name" })).toHaveValue("Jamie edited");
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(next).toHaveBeenCalledOnce());
});
