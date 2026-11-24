import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { DeploymentSettingsLayout } from "./deployment-settings-layout";

const env = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(env.search) }));
beforeEach(() => {
  env.search = "";
});
function fixture(overrides: Partial<ComponentProps<typeof DeploymentSettingsLayout>> = {}) {
  return (
    <DeploymentSettingsLayout
      dirty={false}
      pending={false}
      onSave={vi.fn()}
      onDiscard={vi.fn()}
      identity={
        <>
          <p>Identity fields</p>
          <input aria-label="Deployment name" defaultValue="Original" />
        </>
      }
      access={<p>Access fields</p>}
      notices={<p>Notice fields</p>}
      services={<p>Voice fields</p>}
      operations={<p>Maintenance fields</p>}
      {...overrides}
    />
  );
}
function view() {
  return render(fixture());
}
it.each([
  ["services", "Voice fields"],
  ["operations", "Maintenance fields"],
  ["notices", "Notice fields"],
])("opens the %s section from an optional setup link", (section, label) => {
  env.search = `section=${section}`;
  view();
  expect(screen.getByText(label)).toBeVisible();
  expect(screen.getByText("Identity fields")).not.toBeVisible();
});
it("uses the ordinary first section for an invalid deep link", () => {
  env.search = "section=unknown";
  view();
  expect(screen.getByText("Identity fields")).toBeVisible();
});

it("updates the shareable section URL when a person changes sections", async () => {
  view();
  await userEvent.click(screen.getByRole("tab", { name: "Voice & mobile" }));
  expect(screen.getByText("Voice fields")).toBeVisible();
  expect(new URLSearchParams(window.location.search).get("section")).toBe("services");
});
it("keeps unsaved fields mounted while switching tabs with the keyboard", async () => {
  const user = userEvent.setup();
  view();
  const name = screen.getByRole("textbox", { name: "Deployment name" });
  await user.clear(name);
  await user.type(name, "Changed locally");
  const identity = screen.getByRole("tab", { name: "Identity" });
  identity.focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Access & accounts" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(name).not.toBeVisible();
  await user.keyboard("{ArrowLeft}");
  expect(screen.getByRole("textbox", { name: "Deployment name" })).toBe(name);
  expect(name).toHaveValue("Changed locally");
});
it("follows a changed deep link without remounting or resetting a draft", () => {
  const result = view();
  env.search = "section=notices";
  result.rerender(fixture());
  expect(screen.getByText("Notice fields")).toBeVisible();
  expect(screen.getByText("Identity fields")).not.toBeVisible();
  env.search = "section=access";
  result.rerender(fixture());
  expect(screen.getByText("Access fields")).toBeVisible();
});

it("keeps the same save control disabled until a timing error is corrected", () => {
  const result = render(fixture({ dirty: true, invalid: true }));
  const save = screen.getByRole("button", { name: "Save" });
  const draft = screen.getByRole("textbox", { name: "Deployment name" });
  expect(save).toBeDisabled();
  result.rerender(fixture({ dirty: true, invalid: false }));
  expect(screen.getByRole("button", { name: "Save" })).toBe(save);
  expect(save).toBeEnabled();
  expect(screen.getByRole("textbox", { name: "Deployment name" })).toBe(draft);
});
