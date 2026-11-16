import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatApprovalSelector } from "./chat-approval-selector";
import { useChatControlsStore } from "@/stores/chat-controls-store";

const state = vi.hoisted(() => ({ mayDecide: true, mayWaive: true }));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.mayDecide }),
  useOrganizationList: () => ({
    data: [{ id: "org-1", chat_may_waive_approvals: state.mayWaive }],
  }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (pick: (store: { activeOrgId: string }) => unknown) =>
    pick({ activeOrgId: "org-1" }),
}));
beforeEach(() => {
  state.mayDecide = true;
  state.mayWaive = true;
  useChatControlsStore.setState({ byScope: {} });
});

it("shows and persists the active mode without opening Chat controls", async () => {
  const onChange = vi.fn();
  const view = render(<ChatApprovalSelector onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "Permission mode: Follow the agent" }));
  await userEvent.click(screen.getByRole("menuitemradio", { name: /Approve everything/ }));
  expect(onChange).toHaveBeenCalledWith("approve_all");
  expect(screen.getByRole("button", { name: "Permission mode: Approve everything" })).toBeVisible();
  view.unmount();
  render(<ChatApprovalSelector />);
  expect(screen.getByRole("button", { name: "Permission mode: Approve everything" })).toBeVisible();
});

it.each(["permission", "organization"])(
  "keeps waiving disabled when blocked by %s",
  async (blocked) => {
    state.mayDecide = blocked !== "permission";
    state.mayWaive = blocked !== "organization";
    render(<ChatApprovalSelector />);
    await userEvent.click(
      screen.getByRole("button", { name: "Permission mode: Follow the agent" }),
    );
    expect(screen.getByRole("menuitemradio", { name: /Approve everything/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await userEvent.click(screen.getByRole("menuitemradio", { name: /Ask about everything/ }));
    expect(
      screen.getByRole("button", { name: "Permission mode: Ask about everything" }),
    ).toBeVisible();
  },
);
