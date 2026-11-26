import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { OrganizationConsoleRolePreview } from "./org-console-role-preview";
import type { ConsolePresentation } from "@/lib/console-experience-api";

const presentation: ConsolePresentation = {
  simple_navigation: ["chat"],
  navigation_available: ["chat", "agents"],
  organization_navigation: [],
  navigation: [],
  preferences: {
    navigation: [],
    desktop_install_prompt: false,
    product_notices: false,
  },
  notices_available: { desktop_install_prompt: false },
  organization_notices: { product_notices: true },
  desktop_install_prompt: false,
  product_notices: false,
  available_mcp_gallery: { mode: "allow-list", keys: ["one", "two"] },
};
const props = {
  role: "member" as const,
  selection: ["chat", "agents"],
  presentation,
  can: (permission: string) => permission !== "runs:view",
  managesMcp: false,
  managesSkills: false,
};

it("opens a complete role-default preview without fetching anyone's content", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  render(
    <OrganizationConsoleRolePreview
      {...props}
      defaults={{
        dashboard: {
          entries: [
            { kind: "section", label: "Team home" },
            { widget: "my-agents" },
            { widget: "spend" },
          ],
        },
        mcp_gallery: { mode: "allow-list", keys: ["two", "three"] },
        skill_gallery: { mode: "available", keys: [] },
      }}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Open console preview" }));
  const dialog = screen.getByRole("dialog", { name: "Preview as Member" });
  expect(within(dialog).getByRole("heading", { name: "Team home" })).toBeVisible();
  expect(within(dialog).getByRole("heading", { name: "Your agents" })).toBeVisible();
  expect(within(dialog).queryByRole("heading", { name: "Spend" })).toBeNull();
  expect(within(dialog).getByText("Up to 1 approved entry")).toBeVisible();
  expect(within(dialog).getByText("Only visible installed skills")).toBeVisible();
  const notices = within(dialog).getByRole("region", { name: "Product prompts" });
  expect(within(notices).getByText("Hidden")).toBeVisible();
  expect(within(notices).getByText("Shown")).toBeVisible();
  expect(fetch).not.toHaveBeenCalled();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: "Open console preview" })).toHaveFocus();
  fetch.mockRestore();
});

it("keeps empty defaults intentional and manager bypass within the deployment ceiling", async () => {
  render(
    <OrganizationConsoleRolePreview
      {...props}
      can={() => true}
      selection={[]}
      managesMcp
      defaults={{ dashboard: { entries: [] }, mcp_gallery: { mode: "allow-list", keys: [] } }}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Open console preview" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("No dashboard cards are shown.")).toBeVisible();
  expect(within(dialog).getAllByText("No primary navigation entries are shown.")[0]).toBeVisible();
  expect(within(dialog).getByText("Up to 2 approved entries")).toBeVisible();
});

it("inherits the standard personal landing widgets instead of the organization overview", async () => {
  render(<OrganizationConsoleRolePreview {...props} defaults={undefined} />);
  await userEvent.click(screen.getByRole("button", { name: "Open console preview" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByRole("heading", { name: "Dashboard" })).toBeVisible();
  expect(within(dialog).queryByText("No dashboard cards are shown.")).toBeNull();
});

it("does not preview gallery availability beyond the administrator and target role permissions", async () => {
  render(<OrganizationConsoleRolePreview {...props} can={() => false} defaults={undefined} />);
  await userEvent.click(screen.getByRole("button", { name: "Open console preview" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getAllByText("Unavailable for these permissions")).toHaveLength(2);
  expect(within(dialog).queryByText("Up to 2 approved entries")).toBeNull();
});
