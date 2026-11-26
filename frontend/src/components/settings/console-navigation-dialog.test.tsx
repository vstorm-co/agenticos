import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ConsoleNavigationDialog } from "./console-navigation-dialog";

vi.mock("@/hooks/use-console-experience", () => ({
  useConsoleExperience: () => ({
    organizationId: "org",
    userId: "me",
    data: {
      presentation: {
        preferences: {},
        organization_navigation: ["chat", "eventSources"],
        navigation_default: ["chat"],
      },
    },
    save: { isPending: false, mutate: vi.fn() },
  }),
}));
it("keeps the compact sidebar control named and opens the inherited selection", async () => {
  render(<ConsoleNavigationDialog sidebar compact />);
  const control = screen.getByRole("button", { name: "Customize sidebar" });
  expect(control).toHaveAttribute("title", "Customize sidebar");
  expect(control).toHaveAttribute("data-tour", "sidebar-navigation-customize");
  expect(control).toHaveClass("text-muted-foreground");
  expect(control).not.toHaveClass("mx-auto");
  await userEvent.click(control);
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Chat" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Event sources" })).not.toBeChecked();
});
