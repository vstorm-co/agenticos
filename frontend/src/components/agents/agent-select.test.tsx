import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentSelect } from "./agent-select";

const agents = [
  {
    id: "one",
    slug: "support",
    name: "Support",
    description: "Refunds and returns",
    has_avatar: false,
    avatar_color: null,
  },
  {
    id: "two",
    slug: "shipping",
    name: "Shipping",
    description: null,
    has_avatar: false,
    avatar_color: 3,
  },
];
function mount(props: Partial<Parameters<typeof AgentSelect>[0]> = {}) {
  const onChange = vi.fn();
  render(
    <AgentSelect
      agents={agents}
      value=""
      onChange={onChange}
      placeholder="Choose an agent"
      aria-label="Agent"
      {...props}
    />,
  );
  return onChange;
}
describe("AgentSelect", () => {
  it("shows the chosen agent's actual identity in the field and searches by handle", async () => {
    const choose = mount({ value: "one" });
    const trigger = screen.getByRole("combobox", { name: "Agent" });
    expect(trigger).toHaveTextContent("Support");
    expect(trigger.querySelector('[data-agent-avatar="one"]')).not.toBeNull();
    await userEvent.click(trigger);
    await userEvent.type(screen.getByPlaceholderText("Search agents"), "shipping");
    expect(screen.queryByRole("option", { name: /Support/ })).toBeNull();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(choose).toHaveBeenCalledWith("two");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });
  it("keeps an unmatched search explicit", async () => {
    mount();
    await userEvent.click(screen.getByRole("combobox", { name: "Agent" }));
    await userEvent.type(screen.getByPlaceholderText("Search agents"), "missing");
    expect(screen.getByText("No agents match your search.")).toBeVisible();
  });
  it("announces loading and prevents opening an unfinished list", () => {
    mount({ loading: true });
    expect(screen.getByRole("combobox", { name: "Agent" })).toBeDisabled();
    expect(screen.getByText("Loading agents…")).toBeVisible();
  });
});
