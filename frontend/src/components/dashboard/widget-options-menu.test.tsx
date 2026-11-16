import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { WidgetOptionsMenu } from "./widget-options-menu";

vi.mock("@/hooks", () => ({
  useAgents: () => ({
    agents: [
      { id: "a1", name: "Researcher", slug: "researcher", has_avatar: false, avatar_color: null },
    ],
  }),
  useMembers: () => ({ members: [] }),
}));
vi.mock("@/stores", () => ({ useOrgStore: () => "org1" }));

it("keeps a named agent filter identifiable after selecting a value", async () => {
  const change = vi.fn();
  render(
    <WidgetOptionsMenu
      widget="activity-rhythm"
      title="Activity rhythm"
      options={{ agentId: "a1" }}
      onChange={change}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: /Activity rhythm/ }));
  const agent = screen.getByRole("combobox", { name: "Agent" });
  expect(agent).toHaveTextContent("Researcher");
  await userEvent.click(agent);
  await userEvent.click(screen.getByRole("option", { name: "All agents" }));
  expect(change).toHaveBeenCalledWith(undefined);
});
