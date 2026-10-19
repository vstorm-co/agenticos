import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ViewSwitcher } from "./view-switcher";
import type { DashboardView } from "@/lib/dashboard/layouts";
import type { Group } from "@/types/groups";

/**
 * Whose dashboard is on screen. What matters: only the offered views are
 * drawn, the open one is marked, a single view draws nothing, and the group
 * view names its group and can move to another.
 */

const GROUPS = [
  { id: "g1", name: "Finance", icon: null, member_count: 3 },
  { id: "g2", name: "Sales", icon: "briefcase", member_count: 5 },
] as unknown as Group[];

function renderSwitcher(
  views: DashboardView[],
  view: DashboardView,
  handlers = { onViewChange: vi.fn(), onGroupChange: vi.fn() },
) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ViewSwitcher
        views={views}
        view={view}
        onViewChange={handlers.onViewChange}
        groups={GROUPS}
        groupId={view === "group" ? "g1" : null}
        onGroupChange={handlers.onGroupChange}
      />
    </NextIntlClientProvider>,
  );
  return handlers;
}

describe("ViewSwitcher", () => {
  it("draws the offered views, marks the open one and answers a click", async () => {
    const { onViewChange } = renderSwitcher(["me", "org", "deployment"], "org");

    expect(screen.getByRole("button", { name: "Organization" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByRole("button", { name: "Group" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Deployment" }));
    expect(onViewChange).toHaveBeenCalledWith("deployment");
  });

  it("draws nothing for a reader with one view", () => {
    renderSwitcher(["me"], "me");

    expect(screen.queryByRole("group", { name: "Dashboard view" })).not.toBeInTheDocument();
  });

  it("names the group on its view and moves to another", async () => {
    const { onGroupChange } = renderSwitcher(["me", "org", "group"], "group");

    const picker = screen.getByRole("combobox", { name: "Choose a group" });
    expect(picker).toHaveTextContent("Finance");

    await userEvent.click(picker);
    await userEvent.click(screen.getByRole("option", { name: "Sales" }));

    expect(onGroupChange).toHaveBeenCalledWith("g2");
  });
});
