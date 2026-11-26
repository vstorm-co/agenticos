import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ActionSelection } from "./action-selection";
import { routineActionIdentity, type RoutineActionOption } from "@/lib/routine-actions-api";

vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "Acme Console" }),
}));
const changes = vi.fn<(keys: Set<string>) => void>();
const write: RoutineActionOption = {
  capability_id: "sandbox",
  capability_name: "Sandbox",
  tool_id: "write",
  name: "Write a file",
  consented: false,
  waivable: true,
};
const read: RoutineActionOption = { ...write, tool_id: "read", name: "Read a file" };
const locked: RoutineActionOption = {
  ...write,
  tool_id: "delete",
  name: "Delete protected file",
  waivable: false,
};
const fallback: RoutineActionOption = {
  ...write,
  capability_id: "web_fetch",
  capability_name: null,
  tool_id: "fetch",
  name: "Fetch a page",
};
const personal: RoutineActionOption = {
  connection_id: "personal-mail",
  authorization_generation: "personal-consent",
  endpoint_hash: "personal-endpoint",
  tool_id: "send",
  name: "Send message",
  account_name: "Personal mail",
  account_scope: "personal",
  consented: false,
  waivable: true,
};
const organization: RoutineActionOption = {
  ...personal,
  connection_id: "org-mail",
  authorization_generation: "org-consent",
  endpoint_hash: "org-endpoint",
  account_name: "Shared mail",
  account_scope: "organization",
};
const platform: RoutineActionOption = {
  kind: "platform",
  tool_id: "publish_finding",
  group: "tasks",
  name: "Notify me",
  consented: false,
  waivable: true,
};
const actions = [write, read, locked, fallback, personal, organization, platform];
const key = routineActionIdentity;
function Harness({
  items = actions,
  initial = [],
  disabled = false,
}: {
  items?: RoutineActionOption[];
  initial?: RoutineActionOption[];
  disabled?: boolean;
}) {
  const [selected, setSelected] = useState(new Set(initial.map(key)));
  return (
    <ActionSelection
      items={items}
      selected={selected}
      disabled={disabled}
      onChange={(next) => {
        changes(next);
        setSelected(next);
      }}
    />
  );
}
beforeEach(() => changes.mockClear());

it("names capabilities, platform tools and each physical account separately", () => {
  render(<Harness />);
  expect(screen.getByRole("region", { name: "Capabilities" })).toBeVisible();
  expect(screen.getByRole("group", { name: "Sandbox" })).toBeVisible();
  expect(screen.getByRole("group", { name: "web_fetch" })).toBeVisible();
  expect(
    within(screen.getByRole("region", { name: "Acme Console" })).getByRole("group", {
      name: "Tasks and Inbox",
    }),
  ).toBeVisible();
  for (const account of ["Personal mail · your account", "Shared mail · organization account"])
    expect(
      within(screen.getByRole("region", { name: account })).getByRole("checkbox", {
        name: "Send message",
      }),
    ).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Delete protected file" })).toBeDisabled();
  expect(screen.getByText("Always asks: required by the agent or platform")).toBeVisible();
});

it("keeps same-named MCP actions on their own account identity", async () => {
  render(<Harness />);
  const account = screen.getByRole("region", { name: "Personal mail · your account" });
  await userEvent.click(within(account).getByRole("checkbox", { name: "Send message" }));
  expect(changes).toHaveBeenLastCalledWith(new Set([key(personal)]));
  expect(
    within(screen.getByRole("region", { name: "Shared mail · organization account" })).getByRole(
      "checkbox",
      { name: "Send message" },
    ),
  ).not.toBeChecked();
  await userEvent.click(within(account).getByRole("checkbox", { name: "Send message" }));
  expect(changes).toHaveBeenLastCalledWith(new Set());
});

it("applies a group to eligible hidden matches and never grants a locked action", async () => {
  render(<Harness initial={[personal]} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Search actions" }), "Write a file");
  expect(screen.queryByRole("checkbox", { name: "Read a file" })).toBeNull();
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Select eligible actions in Sandbox" }),
  );
  expect(changes).toHaveBeenLastCalledWith(new Set([key(personal), key(write), key(read)]));
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Select eligible actions in Sandbox" }),
  );
  expect(changes).toHaveBeenLastCalledWith(new Set([key(personal)]));
});

it("shows partial group state and toggles a whole capability section", async () => {
  render(<Harness initial={[write]} />);
  const toggle = screen.getByRole("checkbox", { name: "Select eligible actions in Capabilities" });
  expect(toggle).toBePartiallyChecked();
  await userEvent.click(toggle);
  expect(changes).toHaveBeenLastCalledWith(new Set([key(write), key(read), key(fallback)]));
  expect(toggle).toBeChecked();
  await userEvent.click(toggle);
  expect(changes).toHaveBeenLastCalledWith(new Set());
});

it("replaces the draft with exactly eligible agent defaults despite a search filter", async () => {
  render(<Harness initial={[locked]} />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Search actions" }), "Notify me");
  await userEvent.click(screen.getByRole("button", { name: "Use the agent's settings" }));
  expect(changes).toHaveBeenLastCalledWith(
    new Set(actions.filter((action) => action.waivable).map(key)),
  );
  expect(screen.getByRole("checkbox", { name: "Notify me" })).toBeChecked();
});

it("reports an empty search and restores account sections when cleared", async () => {
  render(<Harness />);
  const search = screen.getByRole("searchbox", { name: "Search actions" });
  await userEvent.type(search, "not an action");
  expect(screen.getByRole("status")).toHaveTextContent("No actions match your search.");
  expect(screen.queryByRole("region")).toBeNull();
  await userEvent.clear(search);
  expect(screen.getByRole("region", { name: "Capabilities" })).toBeVisible();
});

it("locks pending choices and groups that contain only mandatory actions", async () => {
  const view = render(<Harness disabled />);
  for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).toBeDisabled();
  expect(screen.getByRole("button", { name: "Use the agent's settings" })).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox", { name: "Write a file" }));
  expect(changes).not.toHaveBeenCalled();
  view.rerender(<Harness items={[locked]} />);
  expect(
    screen.getByRole("checkbox", { name: "Select eligible actions in Sandbox" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: "Select eligible actions in Capabilities" }),
  ).toBeDisabled();
});

it("renders no selector when the reviewed version has no actions", () => {
  const { container } = render(<Harness items={[]} />);
  expect(container).toBeEmptyDOMElement();
});
