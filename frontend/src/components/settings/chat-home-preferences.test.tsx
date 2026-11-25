import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatHomePreferences } from "./chat-home-preferences";
import { DEFAULT_CHAT_HOME, type ConsoleExperience } from "@/lib/console-experience-api";

const owner = vi.hoisted(() => ({
  organizationId: "first",
  userId: "one",
  data: undefined as ConsoleExperience | undefined,
}));
vi.mock("@/hooks/use-console-experience", () => ({
  useConsoleExperience: () => ({
    ...owner,
    isPending: false,
    error: null,
    save: { isPending: false, mutate: vi.fn() },
    refetch: vi.fn(),
  }),
}));
beforeEach(() => {
  owner.organizationId = "first";
  owner.userId = "one";
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
    await userEvent.click(screen.getByRole("checkbox", { name: "Chat" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    if (kind === "organization") owner.organizationId = "second";
    else owner.userId = "two";
    view.rerender(<ChatHomePreferences />);
    expect(screen.getByRole("checkbox", { name: "Chat" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  },
);

vi.mock("./console-catalog-controls", () => ({ ConsoleCatalogControls: () => null }));
