import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { RoutineAccessReview, RoutineToolOption } from "@/lib/routine-access-api";
import { useOrgStore } from "@/stores";
import type { Trigger } from "@/types/triggers";
import { RoutineAccessDialog } from "./routine-access-dialog";

vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "AgenticOS", logoUrl: null }),
}));

const state = vi.hoisted(() => ({
  data: undefined as RoutineAccessReview | undefined,
  error: null as Error | null,
  loading: false,
  save: vi.fn(),
  saveError: null as Error | null,
  pending: false,
  refetch: vi.fn(),
}));
vi.mock("@/hooks/use-routine-access", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/use-routine-access")>(
    "@/hooks/use-routine-access",
  );
  return {
    isStaleReview: actual.isStaleReview,
    useRoutineAccess: () => ({
      data: state.data,
      isLoading: state.loading,
      error: state.error,
      refetch: state.refetch,
      save: { mutateAsync: state.save, isPending: state.pending, error: state.saveError },
    }),
  };
});

const trigger = { id: "routine", agent_id: "agent", name: "Digest" } as Trigger;

function tool(overrides: Partial<RoutineToolOption> & { tool_id: string }): RoutineToolOption {
  return {
    capability_id: "mail",
    capability_name: "Mail",
    name: overrides.tool_id,
    effect: true,
    agent: "free",
    setting: "allow",
    ...overrides,
  } as RoutineToolOption;
}

function review(overrides: Partial<RoutineAccessReview> = {}): RoutineAccessReview {
  return {
    mode: "reviewed",
    current: true,
    review_reason: null,
    review_token: "token-1",
    version_id: "v1",
    sources: [{ kind: "mcp_account", id: "c1", name: "Work mail" }],
    unavailable_sources: [],
    required_unavailable_sources: [],
    tools: [
      tool({ tool_id: "send", setting: "allow" }),
      tool({ tool_id: "read", effect: false, setting: "allow" }),
      tool({ tool_id: "delete", agent: "ask", setting: "ask" }),
    ],
    unlisted_accounts: [],
    has_delegates: false,
    delegates: "ask",
    can_allow: true,
    allow_blocked_reason: null,
    can_trust: false,
    trust_blocked_reason: "permission",
    ...overrides,
  };
}

const group = (name: string) => screen.getByRole("radiogroup", { name });
const option = (name: string, label: string) =>
  within(group(name)).getByRole("radio", { name: label });

beforeEach(() => {
  vi.clearAllMocks();
  state.data = review();
  state.error = null;
  state.loading = false;
  state.saveError = null;
  state.pending = false;
  state.save.mockResolvedValue(review());
  useOrgStore.setState({ activeOrgId: "org-1" });
});

it("opens on the tools, titled with the routine, and saves every tool's setting", async () => {
  const onClose = vi.fn();
  render(<RoutineAccessDialog trigger={trigger} onClose={onClose} />);
  expect(screen.getByRole("dialog", { name: "Routine access: Digest" })).toBeVisible();
  expect(screen.getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("2 run freely, 1 ask first, 0 off")).toBeVisible();
  const save = screen.getByRole("button", { name: "Save changes" });
  expect(save).toBeDisabled();

  await userEvent.click(option("send", "Off"));
  expect(screen.getByText("1 run freely, 1 ask first, 1 off")).toBeVisible();
  await userEvent.click(save);

  expect(state.save).toHaveBeenCalledWith({
    review_token: "token-1",
    mode: "reviewed",
    tools: [
      { capability_id: "mail", tool_id: "send", setting: "off" },
      { capability_id: "mail", tool_id: "read", setting: "allow" },
      { capability_id: "mail", tool_id: "delete", setting: "ask" },
    ],
    delegates: "ask",
  });
  await waitFor(() => expect(onClose).toHaveBeenCalled());
});

it("locks a tool the agent always asks before to Ask first or Off", () => {
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText("Always asks (the agent requires it)")).toBeVisible();
  const choices = within(group("delete")).getAllByRole("radio");
  expect(choices.map((choice) => choice.textContent)).toEqual(["Ask first", "Off"]);
});

it("refuses Run freely on a tool that changes something without the permission, and says why", async () => {
  state.data = review({ can_allow: false, allow_blocked_reason: "permission" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);

  // The stored allow is narrowed to what the caller may save.
  expect(option("send", "Ask first")).toHaveAttribute("aria-checked", "true");
  const refused = option("send", "Run freely");
  expect(refused).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(refused);
  expect(refused).toHaveAttribute("aria-checked", "false");
  fireEvent.focus(refused);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "Needs permission to decide approvals.",
  );
  // A read is not standing consent and stays free.
  expect(option("read", "Run freely")).not.toHaveAttribute("aria-disabled");
  expect(
    screen.getByText("You may not decide approvals, so tools that change something ask first."),
  ).toBeVisible();
});

it("shows a tool new since the review as asking when it changes something, and marks it", () => {
  state.data = review({
    tools: [
      tool({ tool_id: "send", setting: null }),
      tool({ tool_id: "read", effect: false, setting: null }),
    ],
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getAllByText("New")).toHaveLength(2);
  expect(option("send", "Ask first")).toHaveAttribute("aria-checked", "true");
  expect(option("read", "Run freely")).toHaveAttribute("aria-checked", "true");
  // Nothing touched, but the new tools still need saving.
  expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
});

it("sets all tools from the menu, keeping off tools off except As the agent", async () => {
  state.data = review({ tools: [...review().tools, tool({ tool_id: "archive", setting: "off" })] });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  const setAll = async (label: string) => {
    await userEvent.click(screen.getByRole("button", { name: /^Set all/ }));
    await userEvent.click(await screen.findByRole("menuitemradio", { name: label }));
  };
  // The menu says which choice the settings amount to, and marks it.
  expect(screen.getByRole("button", { name: "Set all: Run freely where allowed" })).toBeVisible();
  await setAll("Ask for everything");
  expect(screen.getByText("0 run freely, 3 ask first, 1 off")).toBeVisible();
  expect(screen.getByRole("button", { name: "Set all: Ask for everything" })).toBeVisible();
  await setAll("Run freely where allowed");
  expect(screen.getByText("2 run freely, 1 ask first, 1 off")).toBeVisible();
  await setAll("As the agent");
  expect(screen.getByText("3 run freely, 1 ask first, 0 off")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Set all: As the agent" }));
  expect(await screen.findByRole("menuitemradio", { name: "As the agent" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await userEvent.keyboard("{Escape}");
  // Turning one tool off keeps the others as allowed: that is still a choice.
  await userEvent.click(option("send", "Off"));
  expect(screen.getByRole("button", { name: "Set all: Run freely where allowed" })).toBeVisible();
  // Asking first where the rest run freely is not any one choice.
  await userEvent.click(option("send", "Ask first"));
  expect(screen.getByRole("button", { name: "Set all: Custom" })).toBeVisible();
});

it("filters tools by search and names accounts personal or organization", async () => {
  state.data = review({
    tools: [
      tool({ tool_id: "send" }),
      {
        connection_id: "c1",
        tool_id: "create_issue",
        name: "create_issue",
        account_name: "GitHub",
        account_scope: "personal",
        effect: true,
        agent: "free",
        setting: "ask",
      },
    ],
    unlisted_accounts: ["Notion"],
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("region", { name: "GitHub · your account" })).toBeVisible();
  expect(screen.getByText(/Check these connections to list their tools: Notion/)).toBeVisible();
  await userEvent.type(screen.getByLabelText("Search tools"), "issue");
  expect(screen.queryByRole("radiogroup", { name: "send" })).toBeNull();
  expect(group("create_issue")).toBeVisible();
  await userEvent.clear(screen.getByLabelText("Search tools"));
  await userEvent.type(screen.getByLabelText("Search tools"), "nothing");
  expect(screen.getByText("No tools match your search.")).toBeVisible();
});

it("offers delegates as one more row and saves its choice", async () => {
  state.data = review({ has_delegates: true, delegates: "ask" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(option("Delegate agents", "Run freely"));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(state.save).toHaveBeenCalledWith(expect.objectContaining({ delegates: "allow" }));
});

it("opens on the sources a blocker concerns and marks an unavailable one", () => {
  state.data = review({
    current: false,
    review_reason: "unavailable",
    unavailable_sources: ["Work mail"],
  });
  render(<RoutineAccessDialog trigger={trigger} initialTab="sources" onClose={vi.fn()} />);
  expect(screen.getByRole("tab", { name: "Sources" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("Unavailable")).toBeVisible();
  expect(
    screen.getByText(
      "Some sources this routine uses are unavailable: Work mail. Check the agent's connections, then save the review again.",
    ),
  ).toBeVisible();
});

it("refuses to save while a required source is unavailable", () => {
  state.data = review({
    required_unavailable_sources: ["Work mail"],
    unavailable_sources: ["Work mail"],
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} onSaved={vi.fn()} />);
  expect(
    screen.getByText(
      "This routine needs sources that are unavailable: Work mail. Restore them before saving.",
    ),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "Save and enable" })).toBeDisabled();
});

it("links the organization's approval settings when the organization refuses", () => {
  state.data = review({ can_allow: false, allow_blocked_reason: "organization" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Open approval settings" })).toHaveAttribute(
    "href",
    "/orgs/org-1/members?tab=governance",
  );
});

it("words a console-only refusal", () => {
  state.data = review({ can_allow: false, allow_blocked_reason: "console" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(
    screen.getByText("Only you, signed in to the console, can let tools run without asking."),
  ).toBeVisible();
});

it("shows the danger zone off, with why, where trusting the agent is not allowed", () => {
  state.data = review({ can_trust: false, trust_blocked_reason: "organization" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText("Danger zone")).toBeVisible();
  expect(screen.getByRole("switch", { name: "Trust the agent" })).toBeDisabled();
  expect(
    screen.getByText("Your organization does not let routines trust their agent.", {
      exact: false,
    }),
  ).toBeVisible();
  expect(screen.getByRole("link", { name: "Open approval settings" })).toHaveAttribute(
    "href",
    "/orgs/org-1/members?tab=governance",
  );
});

it("names no setting to open when the organization is not what stands in the way", () => {
  state.data = review({ can_trust: false, trust_blocked_reason: "permission" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("switch", { name: "Trust the agent" })).toBeDisabled();
  expect(screen.queryByRole("link", { name: "Open approval settings" })).toBeNull();
});

it("trusts the agent only after confirming, and saves the mode", async () => {
  state.data = review({ can_trust: true, trust_blocked_reason: null });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  const trust = screen.getByRole("switch", { name: "Trust the agent" });
  await userEvent.click(trust);
  const confirm = await screen.findByRole("dialog", { name: "Trust the agent?" });
  await userEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
  expect(trust).not.toBeChecked();

  await userEvent.click(trust);
  await userEvent.click(
    within(await screen.findByRole("dialog", { name: "Trust the agent?" })).getByRole("button", {
      name: "Trust the agent",
    }),
  );
  expect(trust).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(state.save).toHaveBeenCalledWith(expect.objectContaining({ mode: "trust_agent" }));
});

it("turns off a trust that is no longer allowed, and says why", async () => {
  state.data = review({
    mode: "trust_agent",
    current: false,
    review_reason: "trust_not_allowed",
    can_trust: false,
    trust_blocked_reason: "event",
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("switch", { name: "Trust the agent" })).not.toBeChecked();
  expect(screen.getByRole("switch", { name: "Trust the agent" })).toBeDisabled();
  expect(
    screen.getByText(
      "A routine started by an event cannot trust its agent. Save its review to run it again.",
    ),
  ).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(state.save).toHaveBeenCalledWith(expect.objectContaining({ mode: "reviewed" }));
});

it("finishes setup by saving and then enabling, or leaves it for later", async () => {
  state.data = review({ current: false, review_reason: "setup" });
  const onSaved = vi.fn().mockResolvedValue(undefined);
  const onClose = vi.fn();
  render(<RoutineAccessDialog trigger={trigger} onClose={onClose} onSaved={onSaved} />);
  await userEvent.click(screen.getByRole("button", { name: "Finish later" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(state.save).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole("button", { name: "Save and enable" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalled());
  expect(state.save.mock.invocationCallOrder[0]).toBeLessThan(onSaved.mock.invocationCallOrder[0]!);
  expect(onClose).toHaveBeenCalledTimes(2);
});

it("stays open and does not enable when the save is refused as stale", async () => {
  const stale = new ApiError(409, "Review its access again.");
  state.save.mockRejectedValue(stale);
  const onSaved = vi.fn();
  const onClose = vi.fn();
  const view = render(
    <RoutineAccessDialog trigger={trigger} onClose={onClose} onSaved={onSaved} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Save and enable" }));
  expect(onSaved).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();

  state.saveError = stale;
  state.data = review({ review_token: "token-2" });
  view.rerender(<RoutineAccessDialog trigger={trigger} onClose={onClose} onSaved={onSaved} />);
  expect(
    screen.getByText(
      "This routine, its agent's sources or its tools changed while you were reviewing. Check the current review and save again.",
    ),
  ).toBeVisible();
});

it("drops choices made on a review that has since changed", async () => {
  const view = render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  await userEvent.click(option("send", "Off"));
  state.data = review({ review_token: "token-2" });
  view.rerender(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(option("send", "Run freely")).toHaveAttribute("aria-checked", "true");
});

it("moves between choices with the arrow keys, past a refused one", async () => {
  state.data = review({ can_allow: false, allow_blocked_reason: "permission" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  option("send", "Ask first").focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(option("send", "Off")).toHaveAttribute("aria-checked", "true");
  await userEvent.keyboard("{ArrowRight}");
  // Wraps past Run freely, which the caller may not choose.
  expect(option("send", "Ask first")).toHaveAttribute("aria-checked", "true");
  await userEvent.keyboard("a");
  expect(option("send", "Ask first")).toHaveAttribute("aria-checked", "true");
});

it("shows a failed read with a retry and nothing to save", async () => {
  state.data = undefined;
  state.error = new Error("boom");
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(state.refetch).toHaveBeenCalled();
});

it("waits for the review while it loads", () => {
  state.data = undefined;
  state.loading = true;
  render(<RoutineAccessDialog trigger={{ ...trigger, name: null }} onClose={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "Routine access" })).toBeVisible();
  expect(screen.queryByRole("tab")).toBeNull();
});

it.each([
  ["sources", "The agent's tools or sources changed since the last review."],
  ["routine_changed", "The routine changed since the last review"],
  ["platform_identity", "The platform MCP server needs this routine to act as its creator."],
] as const)("says why a %s review is needed", (reason, text) => {
  state.data = review({ current: false, review_reason: reason });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText(text, { exact: false })).toBeVisible();
  expect(screen.queryByRole("link")).toBeNull();
});

it("links the approval settings when the organization withdrew trust", () => {
  state.data = review({
    mode: "trust_agent",
    current: false,
    review_reason: "trust_not_allowed",
    trust_blocked_reason: "organization",
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(
    screen.getByText(/Your organization no longer lets routines trust their agent/),
  ).toBeVisible();
  // The banner and the danger zone each lead to the setting that stands in the way.
  expect(screen.getAllByRole("link", { name: "Open approval settings" })).toHaveLength(2);
});

it("shows no settings link outside an organization", () => {
  useOrgStore.setState({ activeOrgId: null });
  state.data = review({ can_allow: false, allow_blocked_reason: "organization" });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.queryByRole("link", { name: "Open approval settings" })).toBeNull();
});

it("names the platform's own tools and sources by the product, grouped as the Builder does", async () => {
  state.data = review({
    tools: [
      {
        kind: "platform",
        tool_id: "list_tasks",
        name: "list_tasks",
        group: "tasks",
        effect: false,
        agent: "free",
        setting: "allow",
      },
    ],
    sources: [
      { kind: "platform", id: "platform", name: "platform" },
      { kind: "skill", id: "s1", name: null, detail: "v2" },
    ],
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("region", { name: "AgenticOS" })).toBeVisible();
  expect(screen.getByText("Tasks and Inbox")).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: "Sources" }));
  expect(screen.getByText("Platform (1)")).toBeInTheDocument();
  expect(screen.getByText("No longer available")).toBeInTheDocument();
});

it("says when there are no tools and no sources", async () => {
  state.data = review({ tools: [], sources: [] });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText("This agent version gives the routine no tools.")).toBeVisible();
  expect(screen.getByRole("button", { name: /^Set all/ })).toBeDisabled();
  await userEvent.click(screen.getByRole("tab", { name: "Sources" }));
  expect(screen.getByText("This routine reaches no sources.")).toBeVisible();
});

it("marks a required unavailable source apart from an optional one", async () => {
  state.data = review({
    sources: [
      { kind: "mcp_account", id: "c1", name: "Work mail" },
      { kind: "mcp_account", id: "c2", name: "Drive" },
    ],
    unavailable_sources: ["Work mail", "Drive"],
    required_unavailable_sources: ["Work mail"],
  });
  render(<RoutineAccessDialog trigger={trigger} initialTab="sources" onClose={vi.fn()} />);
  expect(screen.getByText("Unavailable, required")).toBeVisible();
  expect(screen.getByText("Unavailable")).toBeVisible();
  expect(screen.getAllByRole("link", { name: "Check the agent's connections" }).length).toBe(3);
});

it("keeps the dialog open on a refused save outside setup", async () => {
  state.save.mockRejectedValue(new ApiError(403, "No"));
  const onClose = vi.fn();
  render(<RoutineAccessDialog trigger={trigger} onClose={onClose} />);
  await userEvent.click(option("send", "Ask first"));
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await waitFor(() => expect(state.save).toHaveBeenCalled());
  expect(onClose).not.toHaveBeenCalled();
});

it("cannot be dismissed while saving, and closes with Escape otherwise", async () => {
  const onClose = vi.fn();
  state.pending = true;
  const view = render(<RoutineAccessDialog trigger={trigger} onClose={onClose} />);
  await userEvent.keyboard("{Escape}");
  expect(onClose).not.toHaveBeenCalled();
  state.pending = false;
  view.rerender(<RoutineAccessDialog trigger={trigger} onClose={onClose} />);
  await userEvent.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalled();
});

it("steps back with the left arrow", async () => {
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  option("send", "Run freely").focus();
  await userEvent.keyboard("{ArrowLeft}");
  expect(option("send", "Off")).toHaveAttribute("aria-checked", "true");
});

it("narrows stored delegates to asking when the caller may no longer allow", async () => {
  state.data = review({
    has_delegates: true,
    delegates: "allow",
    can_allow: false,
    allow_blocked_reason: "organization",
    tools: [],
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(option("Delegate agents", "Ask first")).toHaveAttribute("aria-checked", "true");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(state.save).toHaveBeenCalledWith(expect.objectContaining({ delegates: "ask" }));
});

it("names an organization account's tools as the organization's", () => {
  state.data = review({
    tools: [
      {
        connection_id: "c9",
        tool_id: "post",
        name: "post",
        account_name: "Slack",
        account_scope: "organization",
        effect: true,
        agent: "free",
        setting: "ask",
      },
    ],
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByRole("region", { name: "Slack · organization account" })).toBeVisible();
});

it("turns a stored trust off without asking", async () => {
  state.data = review({ mode: "trust_agent", can_trust: true, trust_blocked_reason: null });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  const trust = screen.getByRole("switch", { name: "Trust the agent" });
  expect(trust).toBeChecked();
  await userEvent.click(trust);
  expect(trust).not.toBeChecked();
  expect(screen.queryByRole("dialog", { name: "Trust the agent?" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(state.save).toHaveBeenCalledWith(expect.objectContaining({ mode: "reviewed" }));
});

it("words a refused trust whose reason the server left out", () => {
  state.data = review({
    mode: "trust_agent",
    current: false,
    review_reason: "trust_not_allowed",
    can_trust: false,
    trust_blocked_reason: null,
  });
  render(<RoutineAccessDialog trigger={trigger} onClose={vi.fn()} />);
  expect(screen.getByText("Only you, signed in to the console, can turn this on.")).toBeVisible();
});
