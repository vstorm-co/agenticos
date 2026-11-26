import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { toast } from "sonner";
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
  expect(screen.getByLabelText("Display name")).toBeEnabled();
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

it("saves identity and agent context in one request from the profile tab", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({
    ...USER,
    full_name: "Alex draft",
    job_title: "Engineer",
  });
  render(<ProfileIdentitySettings unifiedSave />);
  expect(screen.getAllByRole("button", { name: /Save/ })).toHaveLength(1);
  await userEvent.type(screen.getByLabelText("Display name"), " draft");
  await userEvent.type(screen.getByLabelText("Your role"), "Engineer");
  await userEvent.click(screen.getByRole("button", { name: /Save/ }));
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledOnce());
  expect(apiClient.patch).toHaveBeenCalledWith(
    "/users/me",
    expect.objectContaining({ full_name: "Alex draft", job_title: "Engineer" }),
  );
});

it("uses the generated portrait after a failed image and retries a newly uploaded version", () => {
  useAuthStore.setState({ user: { ...USER, avatar_url: "avatars/missing.png" }, avatarVersion: 1 });
  render(<ProfileIdentitySettings section="identity" />);
  const portrait = screen.getAllByRole("button", { name: "Replace avatar" })[0];
  if (!portrait) throw new Error("Missing portrait control");
  const image = portrait.querySelector("img");
  if (!image) throw new Error("Missing uploaded portrait");
  fireEvent.error(image);
  expect(portrait.querySelector("img")).toBeNull();
  expect(portrait.querySelector("svg")).not.toBeNull();
  act(() => useAuthStore.setState({ avatarVersion: 2 }));
  expect(portrait.querySelector("img")).toHaveAttribute(
    "src",
    expect.stringContaining("/api/users/avatar/profile-user?v=2"),
  );
});

it("continues onboarding without a no-change toast or profile write", async () => {
  const onContinue = vi.fn();
  render(
    <ProfileIdentitySettings section="identity" onContinue={onContinue} saveLabel="Continue" />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Continue" }));
  expect(onContinue).toHaveBeenCalledOnce();
  expect(apiClient.patch).not.toHaveBeenCalled();
  expect(toast.info).not.toHaveBeenCalled();
});

it("saves an onboarding carousel choice with the existing account contract and retains unsaved identity", async () => {
  const held = Promise.withResolvers<User>();
  vi.mocked(apiClient.patch).mockReturnValueOnce(held.promise);
  render(
    <ProfileIdentitySettings
      section="identity"
      avatarPresentation="carousel"
      onContinue={vi.fn()}
    />,
  );
  await userEvent.type(screen.getByLabelText("Display name"), " draft");
  await userEvent.click(screen.getByRole("button", { name: "Colour 4" }));
  expect(apiClient.patch).toHaveBeenCalledExactlyOnceWith("/users/me", { avatar_color: 4 });
  expect(screen.getByRole("button", { name: "Colour 5" })).toBeDisabled();
  held.resolve({ ...USER, avatar_color: 4 });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Colour 4" })).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
  expect(screen.getByLabelText("Display name")).toHaveValue("Alex draft");
});

it("keeps an uploaded photo primary while choosing a visible carousel fallback", async () => {
  const photo = { ...USER, avatar_url: "avatars/photo.png" };
  useAuthStore.setState({ user: photo });
  vi.mocked(apiClient.patch).mockResolvedValueOnce({ ...photo, avatar_color: 3 });
  render(
    <ProfileIdentitySettings
      section="identity"
      avatarPresentation="carousel"
      onContinue={vi.fn()}
    />,
  );
  const portrait = screen.getAllByRole("button", { name: "Replace avatar" })[0];
  if (!portrait) throw new Error("Missing uploaded portrait control");
  const source = portrait.querySelector("img")?.getAttribute("src");
  expect(source).toBeTruthy();
  expect(screen.getByRole("region", { name: "Choose your look" })).toBeVisible();
  expect(
    screen.getByText("Your photo stays visible. Choose a colour for when it isn’t available."),
  ).toBeVisible();
  expect(screen.queryByRole("button", { name: "Fallback colour" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Colour 3" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Colour 3" })).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
  expect(apiClient.patch).toHaveBeenCalledExactlyOnceWith("/users/me", { avatar_color: 3 });
  expect(apiClient.upload).not.toHaveBeenCalled();
  expect(useAuthStore.getState().user?.avatar_url).toBe(photo.avatar_url);
  expect(portrait.querySelector("img")).toHaveAttribute("src", source);
});

it("keeps identity fields mounted and editable while a carousel colour saves, serializing writes", async () => {
  const photo = { ...USER, avatar_url: "avatars/photo.png" };
  useAuthStore.setState({ user: photo });
  const held = Promise.withResolvers<User>();
  vi.mocked(apiClient.patch).mockReturnValueOnce(held.promise);
  const onContinue = vi.fn();
  const { container } = render(
    <ProfileIdentitySettings
      section="identity"
      avatarPresentation="carousel"
      onContinue={onContinue}
      saveLabel="Continue"
    />,
  );
  const name = screen.getByLabelText("Display name");
  const email = screen.getByLabelText("Email");
  const uploadButtons = screen.getAllByRole("button", { name: "Replace avatar" });
  const replace = uploadButtons.find((button) => button.textContent === "Replace avatar");
  expect(replace).toBeDefined();
  const portrait = container.querySelector("img");
  const source = portrait?.getAttribute("src");
  await userEvent.click(screen.getByRole("button", { name: "Colour 3" }));
  expect(name).toBeEnabled();
  expect(email).toBeEnabled();
  for (const button of uploadButtons) expect(button).toBeDisabled();
  expect(replace).toHaveClass("disabled:opacity-100");
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  await userEvent.type(name, " draft");
  await userEvent.clear(email);
  await userEvent.type(email, "draft@example.com");
  await userEvent.type(name, "{Enter}");
  expect(apiClient.patch).toHaveBeenCalledExactlyOnceWith("/users/me", { avatar_color: 3 });
  expect(apiClient.upload).not.toHaveBeenCalled();
  expect(onContinue).not.toHaveBeenCalled();
  held.resolve({ ...photo, avatar_color: 3 });
  await waitFor(() => expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled());
  expect(screen.getByLabelText("Display name")).toBe(name);
  expect(screen.getByLabelText("Email")).toBe(email);
  expect(screen.getAllByRole("button", { name: "Replace avatar" })).toEqual(uploadButtons);
  expect(container.querySelector("img")).toBe(portrait);
  expect(portrait).toHaveAttribute("src", source);
  expect(name).toHaveValue("Alex draft");
  expect(email).toHaveValue("draft@example.com");
  expect(replace).not.toHaveClass("disabled:opacity-100");
});
