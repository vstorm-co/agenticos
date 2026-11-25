import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { OrganizationConsoleNavigation } from "./org-console-navigation";
import type { ConsolePresentation } from "@/lib/console-experience-api";

const env = vi.hoisted(() => ({
  loading: false,
  error: null as Error | null,
  missing: false,
  can: true,
}));
beforeEach(() => {
  env.loading = false;
  env.error = null;
  env.missing = false;
  env.can = true;
});
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => env.can }),
  useRoleCatalog: () => ({
    catalog: env.missing
      ? undefined
      : {
          roles: [
            { name: "member", permissions: [{ permission: "agents:view", scope: "shared" }] },
            {
              name: "builder",
              permissions: [
                { permission: "agents:view", scope: "all" },
                { permission: "runs:view", scope: "all" },
              ],
            },
          ],
        },
    isLoading: env.loading,
    error: env.error,
  }),
}));
const presentation: ConsolePresentation = {
  simple_navigation: ["chat", "inbox"],
  navigation_available: ["chat", "inbox", "agents", "activity"],
  organization_navigation: [],
  navigation: [],
  preferences: {},
  notices_available: {},
  organization_notices: {},
  desktop_install_prompt: true,
  product_notices: true,
};
it("previews presentation through the selected role, without impersonating anyone", async () => {
  const save = vi.fn();
  render(
    <OrganizationConsoleNavigation
      defaults={{}}
      presentation={presentation}
      disabled={false}
      onSave={save}
    />,
  );
  const preview = screen.getByRole("complementary", { name: "Navigation preview" });
  expect(within(preview).queryByText("Activity")).toBeNull();
  expect(within(preview).getByText("Agents")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Simple assistant" }));
  await waitFor(() => expect(screen.getByRole("combobox", { name: "Role" })).toBeDisabled());
  expect(within(preview).queryByText("Agents")).toBeNull();
  expect(save).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(save.mock.calls[0]?.[0]).toBe("member");
  expect(save.mock.calls[0]?.[1]).toEqual({ navigation: ["chat", "inbox"] });
});

it("changes the preview role while preserving the current user's permission ceiling", async () => {
  const props = { defaults: {}, presentation, disabled: false, onSave: vi.fn() };
  const view = render(<OrganizationConsoleNavigation {...props} />);
  await userEvent.click(screen.getByRole("combobox", { name: "Role" }));
  await userEvent.click(screen.getByRole("option", { name: "Builder" }));
  expect(within(screen.getByRole("complementary")).getByText("Activity")).toBeVisible();
  env.can = false;
  view.rerender(<OrganizationConsoleNavigation {...props} />);
  expect(within(screen.getByRole("complementary")).queryByText("Activity")).toBeNull();
});
it.each(["loading", "error", "missing"])(
  "does not pretend the role catalog loaded when %s",
  (state) => {
    env.loading = state === "loading";
    env.error = state === "error" ? new Error("Unavailable") : null;
    env.missing = state === "missing";
    render(
      <OrganizationConsoleNavigation
        defaults={{}}
        presentation={presentation}
        disabled={false}
        onSave={vi.fn()}
      />,
    );
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  },
);
