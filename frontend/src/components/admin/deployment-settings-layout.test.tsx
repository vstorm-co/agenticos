import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { DeploymentSettingsLayout } from "./deployment-settings-layout";

const env = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(env.search) }));
beforeEach(() => {
  env.search = "";
});
function fixture() {
  return (
    <DeploymentSettingsLayout
      dirty={false}
      pending={false}
      onSave={vi.fn()}
      onDiscard={vi.fn()}
      identity={<p>Identity fields</p>}
      access={<p>Access fields</p>}
      notices={<p>Notice fields</p>}
      services={<p>Voice fields</p>}
      operations={<p>Maintenance fields</p>}
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
  await userEvent.click(screen.getByRole("button", { name: "Voice & mobile" }));
  expect(screen.getByText("Voice fields")).toBeVisible();
  expect(new URLSearchParams(window.location.search).get("section")).toBe("services");
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
