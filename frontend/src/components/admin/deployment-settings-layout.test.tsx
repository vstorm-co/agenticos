import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { DeploymentSettingsLayout } from "./deployment-settings-layout";

const env = vi.hoisted(() => ({ search: "" }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(env.search) }));
beforeEach(() => {
  env.search = "";
});
function view() {
  return render(
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
    />,
  );
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
