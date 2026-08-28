import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatControls } from "./chat-controls";

const state = vi.hoisted(() => ({
  profiles: [] as { id: string; label: string; provider: string; model: string }[],
  conversationId: null as string | null,
  // Both halves of "may this session waive approvals": the caller's permission
  // and the organization's ceiling (#925).
  mayDecide: true,
  orgAllowsWaiving: true,
}));

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: state.profiles,
    createProfile: { mutateAsync: vi.fn(), isPending: false },
  }),
  useProviderModels: () => ({ models: [], source: "curated", isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
  useSecrets: () => ({ secrets: [] }),
  usePermissions: () => ({ can: () => state.mayDecide }),
  useOrganizationList: () => ({
    data: [{ id: "org-1", chat_may_waive_approvals: state.orgAllowsWaiving }],
  }),
}));
vi.mock("@/stores", () => ({
  useConversationStore: (pick: (state: unknown) => unknown) =>
    pick({ currentConversationId: state.conversationId }),
  useOrgStore: (pick: (state: unknown) => unknown) => pick({ activeOrgId: "org-1" }),
}));

// The picker is tested on its own; here it only needs to be able to choose.
vi.mock("./chat-model-picker", () => ({
  ChatModelPicker: ({
    value,
    onChange,
  }: {
    value: string | null;
    onChange: (next: string | null) => void;
  }) => (
    <button type="button" onClick={() => onChange("p-1")}>
      pick a model ({value ?? "none"})
    </button>
  ),
}));

function open(props: Partial<Parameters<typeof ChatControls>[0]> = {}) {
  const handlers = { onModelProfileChange: vi.fn(), ...props };
  render(<ChatControls {...handlers} />);
  return handlers;
}

const trigger = () => screen.getByRole("button", { name: /Chat controls/ });

beforeEach(() => {
  state.profiles = [{ id: "p-1", label: "openai default", provider: "openai", model: "gpt-4.1" }];
  state.conversationId = null;
  state.mayDecide = true;
  state.orgAllowsWaiving = true;
});

describe("the chat controls trigger", () => {
  it("is reachable by the /settings slash command", () => {
    // The command's only handle on this popover is a DOM query for the data
    // attribute (see ChatContainer's slashContext.openSettings). If the
    // attribute drops off the trigger, /settings silently does nothing.
    render(<ChatControls />);

    const found = screen.getByRole("button", { name: "Chat controls" });
    expect(document.querySelector("[data-chat-settings-trigger]")).toBe(found);
  });

  it("says only 'Controls' until the model is overridden", () => {
    open();

    expect(trigger()).toHaveTextContent("Controls");
  });

  it("names the model this conversation was moved onto", async () => {
    // The trigger is the only place an override is visible once the popover is
    // closed, and an override nobody can see is one nobody remembers making.
    const handlers = open();
    await userEvent.click(trigger());

    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));

    expect(handlers.onModelProfileChange).toHaveBeenCalledWith("p-1");
    expect(trigger()).toHaveTextContent("openai default");
  });

  it("offers a way back to the agent's own model, once there is one to go back from", async () => {
    // There is no "organization default" row: an agent names its own model, and
    // leaving that alone is what no override means.
    const handlers = open();
    await userEvent.click(trigger());
    expect(screen.queryByRole("button", { name: /Back to the agent/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));
    await userEvent.click(screen.getByRole("button", { name: /Back to the agent/ }));

    expect(handlers.onModelProfileChange).toHaveBeenLastCalledWith(null);
    expect(trigger()).toHaveTextContent("Controls");
  });

  it("says whether the override is saved yet", async () => {
    // Before the first turn there is no conversation to save it against.
    const { unmount } = render(<ChatControls onModelProfileChange={vi.fn()} />);
    await userEvent.click(trigger());
    expect(screen.getByText("Saves on send")).toBeInTheDocument();
    unmount();

    state.conversationId = "c-1";
    render(<ChatControls onModelProfileChange={vi.fn()} />);
    await userEvent.click(trigger());
    expect(screen.getByText("Saved for this chat")).toBeInTheDocument();
  });

  it("names a model that is no longer in the organization's list as no model", async () => {
    // A key rotated away takes its profile with it; the trigger must not claim an
    // override it cannot name.
    state.profiles = [];
    open();
    await userEvent.click(trigger());

    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));

    expect(trigger()).toHaveTextContent("Controls");
  });
});

describe("the approval mode", () => {
  /**
   * How much this conversation wants to be asked, whatever the agent's spec says
   * (#925). The spec decides at publish time and per tool, which is right for a
   * statement about what the agent *is* - and useless to somebody working through
   * twenty turns with an agent that gates three tools.
   *
   * Two of the three options carry a gate, and each absence means something
   * different: waiving needs the permission *and* the organization's leave, while
   * tightening needs neither.
   */
  async function openControls() {
    render(<ChatControls />);
    await userEvent.click(screen.getByRole("button", { name: "Chat controls" }));
  }

  it("follows the agent until somebody says otherwise", async () => {
    await openControls();

    expect(screen.getByRole("radio", { name: /Follow the agent/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reports the chosen mode to its caller", async () => {
    const onApprovalModeChange = vi.fn();
    render(<ChatControls onApprovalModeChange={onApprovalModeChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Chat controls" }));

    await userEvent.click(screen.getByRole("radio", { name: /Ask about everything/ }));

    expect(onApprovalModeChange).toHaveBeenCalledWith("ask_all");
  });

  it("offers waiving to somebody who may decide, in an organization that allows it", async () => {
    await openControls();

    expect(screen.getByRole("radio", { name: /Approve everything/ })).toBeEnabled();
  });

  it("refuses waiving to a caller without approvals:decide, and says why", async () => {
    // A standing consent *is* the decision the approval queue exists to record,
    // and `member` and `builder` run agents without holding it.
    state.mayDecide = false;
    await openControls();

    expect(screen.getByRole("radio", { name: /Approve everything/ })).toBeDisabled();
    expect(screen.getByText(/Waiving approvals needs permission/)).toBeVisible();
  });

  it("refuses waiving where the organization has not allowed it", async () => {
    // The ceiling, and it can be shut for an owner: without one, a Builder's
    // deliberate gate is one click from nothing in every conversation.
    state.orgAllowsWaiving = false;
    await openControls();

    expect(screen.getByRole("radio", { name: /Approve everything/ })).toBeDisabled();
  });

  it("still offers tightening to everybody", async () => {
    // It only ever adds questions, so it needs no permission and no ceiling.
    state.mayDecide = false;
    state.orgAllowsWaiving = false;
    await openControls();

    expect(screen.getByRole("radio", { name: /Ask about everything/ })).toBeEnabled();
  });

  it("marks the trigger as overridden once the mode is not the agent's", async () => {
    // The dot is what says "this conversation is not running the defaults" - and
    // an approval mode is as much an override as a model is.
    await openControls();

    await userEvent.click(screen.getByRole("radio", { name: /Ask about everything/ }));

    expect(screen.getByRole("button", { name: "Chat controls" })).toContainHTML("rounded-full");
  });
});
