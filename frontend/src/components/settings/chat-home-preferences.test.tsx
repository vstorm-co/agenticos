import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatHomePreferences } from "./chat-home-preferences";
import { ConsoleNavigationDialog } from "./console-navigation-dialog";
import { DEFAULT_CHAT_HOME, type ConsoleExperience } from "@/lib/console-experience-api";

const owner = vi.hoisted(() => ({
  organizationId: "first",
  userId: "one",
  data: undefined as ConsoleExperience | undefined,
  save: vi.fn(),
  pending: false,
}));
vi.mock("@/hooks/use-console-experience", () => ({
  useConsoleExperience: () => ({
    ...owner,
    isPending: false,
    error: null,
    save: { isPending: owner.pending, mutate: owner.save },
    refetch: vi.fn(),
  }),
}));
beforeEach(() => {
  owner.organizationId = "first";
  owner.userId = "one";
  owner.pending = false;
  owner.save.mockReset();
  owner.data = {
    availability: DEFAULT_CHAT_HOME,
    organization_defaults: {},
    preferences: {},
    effective: DEFAULT_CHAT_HOME,
    reminders: {
      availability: true,
      organization_defaults: {},
      preferences: {},
      effective: { enabled: true, snooze_days: 1 },
    },
    presentation: {
      simple_navigation: ["chat", "inbox"],
      navigation_available: ["chat", "inbox"],
      organization_navigation: ["chat", "inbox"],
      navigation: ["chat", "inbox"],
      preferences: {},
      notices_available: {},
      organization_notices: {},
      desktop_install_prompt: true,
      product_notices: true,
    },
  };
});
it.each(["organization", "account"])(
  "never carries a navigation draft across a cached %s switch",
  async (kind) => {
    const view = render(<ChatHomePreferences />);
    await userEvent.click(screen.getByRole("button", { name: "Customize sidebar" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Chat" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    if (kind === "organization") owner.organizationId = "second";
    else owner.userId = "two";
    view.rerender(<ChatHomePreferences />);
    await userEvent.click(screen.getByRole("button", { name: "Customize sidebar" }));
    expect(screen.getByRole("checkbox", { name: "Chat" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  },
);

vi.mock("./console-catalog-controls", () => ({ ConsoleCatalogControls: () => null }));

it("edits navigation from the compact sidebar and closes only after the save succeeds", async () => {
  owner.save.mockImplementation((_changes, onSaved) => onSaved());
  render(<ConsoleNavigationDialog sidebar compact />);
  await userEvent.click(screen.getByRole("button", { name: "Customize sidebar" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Chat" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.getByRole("dialog")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(owner.save).toHaveBeenCalledWith(
    { console: { navigation: ["inbox"] } },
    expect.any(Function),
  );
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("preserves an unsaved selection on refusal and lets the user discard before closing", async () => {
  render(<ConsoleNavigationDialog sidebar />);
  await userEvent.click(screen.getByRole("button", { name: "Customize sidebar" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "Inbox" }));
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Inbox" })).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("does not offer a personal navigation editor before policy is loaded", () => {
  owner.data = undefined;
  render(<ConsoleNavigationDialog sidebar />);
  expect(screen.queryByRole("button")).toBeNull();
});
