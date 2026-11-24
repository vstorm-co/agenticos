import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatApprovalSelector } from "./chat-approval-selector";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import { useChatControlsStore } from "@/stores/chat-controls-store";

const state = vi.hoisted(() => ({ mayDecide: true, mayWaive: true, mayConfigure: false }));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({
    can: (permission: Permission) =>
      permission === Perm.approvalsDecide ? state.mayDecide : state.mayConfigure,
  }),
  useOrganizationList: () => ({
    data: [{ id: "org-1", chat_may_waive_approvals: state.mayWaive }],
  }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (pick: (store: { activeOrgId: string }) => unknown) =>
    pick({ activeOrgId: "org-1" }),
}));
beforeEach(() => {
  state.mayConfigure = false;
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

it("shows an icon-only mode with an accessible name and updates its shield", async () => {
  render(<ChatApprovalSelector iconOnly />);
  const trigger = screen.getByRole("button", { name: "Permission mode: Follow the agent" });
  expect(trigger.textContent).toBe("");
  expect(trigger).toHaveAttribute("title", "Permission mode: Follow the agent");
  expect(trigger).toHaveAttribute("data-approval-mode", "follow_agent");
  await userEvent.click(trigger);
  await userEvent.click(screen.getByRole("menuitemradio", { name: /Ask about everything/ }));
  expect(trigger).toHaveAttribute("data-approval-mode", "ask_all");
  expect(trigger.querySelector("svg")).toHaveClass("lucide-hand");
  await userEvent.click(trigger);
  await userEvent.click(screen.getByRole("menuitemradio", { name: /Approve everything/ }));
  expect(trigger).toHaveAttribute("data-approval-mode", "approve_all");
  expect(trigger.querySelector("svg")).toHaveClass("lucide-shield-alert");
  expect(trigger).toHaveAttribute("aria-label", "Permission mode: Approve everything");
});

it("links directly to the active organization's approval settings when the mode is disabled", async () => {
  state.mayWaive = false;
  render(<ChatApprovalSelector />);
  await userEvent.click(screen.getByRole("button", { name: "Permission mode: Follow the agent" }));
  expect(screen.getByRole("menuitem", { name: "Open approval settings" })).toHaveAttribute(
    "href",
    "/orgs/org-1/members?tab=governance",
  );
});

it("does not offer a settings destination that the member cannot open", async () => {
  state.mayWaive = false;
  state.mayDecide = false;
  render(<ChatApprovalSelector />);
  await userEvent.click(screen.getByRole("button", { name: "Permission mode: Follow the agent" }));
  expect(
    screen.queryByRole("menuitem", { name: "Open approval settings" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/Ask an organization administrator/)).toBeVisible();
});

it("offers the settings link to an organization configurator without approval decision permission", async () => {
  state.mayWaive = false;
  state.mayDecide = false;
  state.mayConfigure = true;
  render(<ChatApprovalSelector />);
  await userEvent.click(screen.getByRole("button", { name: "Permission mode: Follow the agent" }));
  expect(screen.getByRole("menuitem", { name: "Open approval settings" })).toHaveAttribute(
    "href",
    "/orgs/org-1/members?tab=governance",
  );
  expect(screen.getByRole("menuitemradio", { name: /Approve everything/ })).toHaveAttribute(
    "aria-disabled",
    "true",
  );
});
