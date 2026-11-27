import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { OrganizationChatCostControl, PersonalChatCostControl } from "./chat-cost-controls";
import type { ChatCostPolicy } from "@/lib/console-experience-api";

const policy: ChatCostPolicy = {
  availability: true,
  organization_policy: "everyone",
  preference: null,
  permitted: true,
  effective: true,
};
it("lets the organization select a restricted audience", async () => {
  const onChange = vi.fn();
  render(<OrganizationChatCostControl value="everyone" disabled={false} onChange={onChange} />);
  await userEvent.click(screen.getByRole("combobox", { name: "Who sees costs in chat" }));
  await userEvent.click(screen.getByRole("option", { name: "People with access to spend" }));
  expect(onChange).toHaveBeenCalledWith("spend_privileged");
});
it("lets a person hide, show and inherit within their ceiling", async () => {
  const onChange = vi.fn();
  const view = render(
    <PersonalChatCostControl policy={policy} disabled={false} onChange={onChange} />,
  );
  for (const [label, value] of [
    ["Hide", false],
    ["Show", true],
    ["Inherit (shown)", null],
  ] as const) {
    await userEvent.click(screen.getByRole("combobox", { name: "Show costs in my chats" }));
    await userEvent.click(screen.getByRole("option", { name: label }));
    expect(onChange).toHaveBeenLastCalledWith(value);
    view.rerender(
      <PersonalChatCostControl
        policy={{ ...policy, preference: value }}
        disabled={false}
        onChange={onChange}
      />,
    );
  }
});
it("never offers an escape from an organization restriction", () => {
  render(
    <PersonalChatCostControl
      policy={{ ...policy, permitted: false, effective: false, preference: true }}
      disabled={false}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByRole("combobox")).toBeDisabled();
  expect(screen.getByText(/hides chat costs for this account/)).toBeVisible();
});
