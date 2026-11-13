import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ProfileIdentitySettings } from "./profile-identity-settings";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

vi.mock("@/hooks", () => ({ useAuth: () => ({ user: useAuthStore((state) => state.user) }) }));
vi.mock("@/lib/api-client", () => ({ apiClient: { patch: vi.fn(), upload: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const USER: User = {
  id: "profile-user",
  email: "alex@example.com",
  full_name: "Alex",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  job_title: null,
  about: null,
  time_zone: "UTC",
  working_hours: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: USER });
});

it("freezes both forms for a refused context save and retries the unchanged draft", async () => {
  const held = Promise.withResolvers<User>();
  vi.mocked(apiClient.patch)
    .mockReturnValueOnce(held.promise)
    .mockResolvedValueOnce({
      ...USER,
      job_title: "Customer lead",
      about: "Support",
      working_hours: { days: [1], start: "08:30", end: "16:30" },
    });
  render(<ProfileIdentitySettings />);
  await userEvent.type(screen.getByLabelText("Display name"), " draft");
  await userEvent.type(screen.getByLabelText("Your role"), "Customer lead");
  await userEvent.type(screen.getByLabelText("What you work on"), "Support");
  await userEvent.click(screen.getByRole("button", { name: "Mon" }));
  await userEvent.clear(screen.getByLabelText("Starts at"));
  await userEvent.type(screen.getByLabelText("Starts at"), "08:30");
  await userEvent.clear(screen.getByLabelText("Ends at"));
  await userEvent.type(screen.getByLabelText("Ends at"), "16:30");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  for (const label of [
    "Display name",
    "Email",
    "Your role",
    "What you work on",
    "Starts at",
    "Ends at",
  ]) {
    expect(screen.getByLabelText(label)).toBeDisabled();
  }
  expect(screen.getByRole("combobox", { name: "Time zone" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Mon" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  for (const button of screen.getAllByRole("button", { name: "Upload avatar" }))
    expect(button).toBeDisabled();
  held.reject(new Error("refused"));
  await waitFor(() => expect(screen.getByLabelText("Your role")).toBeEnabled());
  expect(screen.getByLabelText("Your role")).toHaveValue("Customer lead");
  expect(screen.getByLabelText("Display name")).toHaveValue("Alex draft");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(useAuthStore.getState().user?.job_title).toBe("Customer lead"));
  expect(apiClient.patch).toHaveBeenLastCalledWith("/users/me", {
    job_title: "Customer lead",
    about: "Support",
    time_zone: "UTC",
    working_hours: { days: [1], start: "08:30", end: "16:30" },
  });
  expect(screen.getByLabelText("Display name")).toHaveValue("Alex draft");
});

it("keeps the name draft during a color change and submits identity with Enter", async () => {
  const held = Promise.withResolvers<User>();
  vi.mocked(apiClient.patch)
    .mockReturnValueOnce(held.promise)
    .mockResolvedValueOnce({ ...USER, full_name: "Alex draft", avatar_color: 3 });
  render(<ProfileIdentitySettings />);
  await userEvent.type(screen.getByLabelText("Display name"), " draft");
  await userEvent.click(screen.getByRole("button", { name: "Fallback colour" }));
  await userEvent.click(screen.getByRole("radio", { name: "Colour 3" }));
  expect(screen.getByLabelText("Display name")).toBeDisabled();
  expect(screen.getByRole("radio", { name: "Colour 4" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  held.resolve({ ...USER, avatar_color: 3 });
  await waitFor(() => expect(screen.getByLabelText("Display name")).toBeEnabled());
  expect(screen.getByLabelText("Display name")).toHaveValue("Alex draft");
  await userEvent.type(screen.getByLabelText("Display name"), "{Enter}");
  await waitFor(() => expect(useAuthStore.getState().user?.full_name).toBe("Alex draft"));
  expect(apiClient.patch).toHaveBeenLastCalledWith("/users/me", { full_name: "Alex draft" });
});

it("unlocks a refused portrait upload and accepts retrying the same file", async () => {
  const held = Promise.withResolvers<User>();
  vi.mocked(apiClient.upload)
    .mockReturnValueOnce(held.promise)
    .mockResolvedValueOnce({ ...USER, avatar_url: "avatars/test.png" });
  const { container } = render(<ProfileIdentitySettings />);
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("Missing portrait input");
  const file = new File(["local fixture"], "portrait.png", { type: "image/png" });
  await userEvent.upload(input, file);
  expect(screen.getByLabelText("Display name")).toBeDisabled();
  expect(screen.getByLabelText("Your role")).toBeDisabled();
  held.reject(new Error("refused"));
  await waitFor(() => expect(screen.getByLabelText("Display name")).toBeEnabled());
  expect(input).toHaveValue("");
  await userEvent.upload(input, file);
  await waitFor(() => expect(useAuthStore.getState().user?.avatar_url).toBe("avatars/test.png"));
  expect(apiClient.upload).toHaveBeenCalledTimes(2);
});
