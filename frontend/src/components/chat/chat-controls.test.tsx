import { useChatControlsStore } from "@/stores/chat-controls-store";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkOnStore } from "@/stores/work-on-store";
import { ChatControls } from "./chat-controls";

const state = vi.hoisted(() => ({
  desktop: false,
  profiles: [] as { id: string; label: string; provider: string; model: string }[],
  conversationId: null as string | null,
  // Both halves of "may this session waive approvals": the caller's permission
  // and the organization's ceiling (#925).
  mayDecide: true,
  orgAllowsWaiving: true,
  orgLoaded: true,
  pathname: "/chat",
  openPage: vi.fn(),
  personalHarness: null as "claude_code" | "codex" | null,
}));

vi.mock("@/hooks/use-shell", () => ({
  useShell: () => (state.desktop ? { platform: "macos" } : null),
}));
vi.mock("./work-on", () => ({
  WorkOn: () =>
    state.desktop ? (
      <section aria-label="Work environment">
        <p>Browser</p>
        <p>Sandbox</p>
      </section>
    ) : null,
  ConversationNotifications: () => (state.desktop ? <p>Conversation notifications</p> : null),
}));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("@/stores/onboarding-store", () => ({
  useOnboardingStore: (pick: (store: unknown) => unknown) => pick({ openPage: state.openPage }),
}));

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: state.profiles,
    createProfile: { mutateAsync: vi.fn(), isPending: false },
  }),
  useProviderModels: () => ({ models: [], refused: [], source: "curated", isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
  useSecrets: () => ({ secrets: [] }),
  usePermissions: () => ({ can: () => state.mayDecide }),
  useOrganizationList: () => ({
    data: state.orgLoaded
      ? [{ id: "org-1", chat_may_waive_approvals: state.orgAllowsWaiving }]
      : [],
  }),
}));
vi.mock("@/stores", () => ({
  useConversationStore: (pick: (state: unknown) => unknown) =>
    pick({ currentConversationId: state.conversationId }),
  useOrgStore: (pick: (state: unknown) => unknown) => pick({ activeOrgId: "org-1" }),
  useAgentSelectionStore: (pick: (state: unknown) => unknown) =>
    pick({ selectedAgentId: "agent-1" }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [{ id: "agent-1", personal_coding_harness: state.personalHarness }],
  }),
}));

// The agent's own-account section is tested on its own, and reads hooks this
// file does not stage.
vi.mock("./remembered-approvals", () => ({ RememberedApprovals: () => null }));
vi.mock("./your-connections", () => ({ YourConnections: () => null }));
vi.mock("@/components/settings/coding-accounts", () => ({
  PersonalCodingAccount: ({ harness }: { harness: string }) => (
    <section aria-label={`Your ${harness} account`} />
  ),
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
  useChatControlsStore.setState({ byScope: {} });
  state.desktop = false;
  useWorkOnStore.setState({ byConversation: {}, draft: null, draftProjectKey: null });
  state.profiles = [{ id: "p-1", label: "openai default", provider: "openai", model: "gpt-4.1" }];
  state.conversationId = null;
  state.mayDecide = true;
  state.orgAllowsWaiving = true;
  state.orgLoaded = true;
  state.pathname = "/chat";
  state.openPage = vi.fn();
  state.personalHarness = null;
});

describe("the page's tips", () => {
  it("are replayed from the controls, which close first so the tour can walk them (#2301)", async () => {
    render(<ChatControls />);
    await userEvent.click(trigger());

    await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));
    await userEvent.click(screen.getByRole("button", { name: "Show tips for this page" }));

    expect(state.openPage).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });

  it("are not offered where the page has none", async () => {
    state.pathname = "/admin/users";
    render(<ChatControls />);
    await userEvent.click(trigger());

    expect(screen.queryByRole("button", { name: "Show tips for this page" })).toBeNull();
  });
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

  it("stays open under the page tour's caption, and closes on an outside click otherwise", async () => {
    // The tour walks the popover's sections: its caption sits outside the popover,
    // and closing on it left the next stop pinned to a section that had gone.
    render(<ChatControls onModelProfileChange={vi.fn()} />);
    const caption = document.createElement("div");
    caption.className = "driver-popover";
    caption.style.pointerEvents = "auto";
    document.body.appendChild(caption);
    await userEvent.click(trigger());
    await userEvent.click(caption);
    expect(screen.getByText("Changes are saved automatically")).toBeInTheDocument();

    caption.remove();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByText("Changes are saved automatically")).toBeNull();
  });

  it("is one icon, titled 'Chat controls' when the agent's model could not be read", () => {
    open();

    expect(trigger()).toHaveTextContent("");
    expect(trigger()).toHaveAttribute("title", "Chat controls");
  });

  it("names the agent's own model until the conversation overrides it", () => {
    // An icon says nothing about which model answers, so its tooltip does.
    open({
      agentModel: {
        profile_id: "agent-profile",
        provider: "anthropic",
        model: "claude-sonnet-5-5",
        label: "Sonnet 5.5",
      },
    });

    expect(trigger()).toHaveAttribute("title", "Model: Sonnet 5.5");
    expect(screen.queryByTestId("override-dot")).toBeNull();
  });

  it("names the model this conversation was moved onto", async () => {
    // The trigger is the only place an override is visible once the popover is
    // closed, and an override nobody can see is one nobody remembers making.
    const handlers = open();
    await userEvent.click(trigger());

    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));

    expect(handlers.onModelProfileChange).toHaveBeenCalledWith("p-1");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(trigger()).toHaveAttribute("title", "Model: openai default");
    expect(screen.getByTestId("override-dot")).toBeInTheDocument();
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
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(trigger()).toHaveAttribute("title", "Chat controls");
    expect(screen.queryByTestId("override-dot")).toBeNull();
  });

  it("says whether the override is saved yet", async () => {
    // Before the first turn there is no conversation to save it against.
    const { unmount } = render(<ChatControls onModelProfileChange={vi.fn()} />);
    await userEvent.click(trigger());
    expect(screen.getByText("Changes are saved automatically")).toBeInTheDocument();
    unmount();

    state.conversationId = "c-1";
    render(<ChatControls onModelProfileChange={vi.fn()} />);
    await userEvent.click(trigger());
    expect(screen.getByText("Changes are saved automatically")).toBeInTheDocument();
  });

  it("names a model that is no longer in the organization's list as no model", async () => {
    // A key rotated away takes its profile with it; the trigger must not claim an
    // override it cannot name.
    state.desktop = false;
    useWorkOnStore.setState({ byConversation: {}, draft: null, draftProjectKey: null });
    state.profiles = [];
    open();
    await userEvent.click(trigger());

    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(trigger()).toHaveAttribute("title", "Chat controls");
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
    await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));
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
    await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));

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
    expect(screen.getByText(/You need permission to decide approvals/)).toBeVisible();
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

    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByRole("button", { name: "Chat controls" })).toContainHTML("rounded-full");
  });
});

it("keeps the composer controls free of a duplicate folder badge", () => {
  state.desktop = true;
  useWorkOnStore.getState().set(null, { folder: "/approved/Launch", mode: "read_only" });
  open();
  expect(screen.queryByRole("button", { name: /Working in \/approved\/Launch/i })).toBeNull();
  expect(trigger()).toBeVisible();
});

it("separates model, tools and preferences and can return without losing them", async () => {
  state.desktop = true;
  open();
  await userEvent.click(trigger());
  expect(screen.getByRole("button", { name: /pick a model/ })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Work environment" })).toBeNull();
  await userEvent.click(screen.getByRole("tab", { name: "Tools & files" }));
  expect(screen.getByRole("region", { name: "Work environment" })).toBeVisible();
  expect(screen.queryByRole("button", { name: /pick a model/ })).toBeNull();
  await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));
  expect(screen.queryByRole("region", { name: "Work environment" })).toBeNull();
  expect(screen.getByRole("radiogroup")).toBeVisible();
  expect(screen.getByText("Conversation notifications")).toBeVisible();
  await userEvent.click(screen.getByRole("tab", { name: "Tools & files" }));
  expect(screen.getByRole("region", { name: "Work environment" })).toBeVisible();
});

describe("the compact settings panel", () => {
  it("opens on the panel and closes explicitly without changing choices", async () => {
    const change = vi.fn();
    open({ onApprovalModeChange: change });
    await userEvent.click(trigger());
    expect(screen.getByRole("dialog", { name: "Chat controls" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(change).not.toHaveBeenCalled();
    expect(trigger()).toHaveFocus();
  });

  it("explains available permission modes before they are selected", async () => {
    open();
    await userEvent.click(trigger());
    const askHint =
      "Ask before every tool this agent can use, including the ones it does not normally gate.";
    expect(screen.getByText(askHint)).not.toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));
    expect(screen.getByText(askHint)).toBeVisible();
  });
});

it("explains an organization policy refusal and links directly to its approval settings", async () => {
  state.orgAllowsWaiving = false;
  open();
  await userEvent.click(trigger());
  await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));
  expect(screen.getByRole("radio", { name: "Approve everything" })).toBeDisabled();
  expect(screen.getByText(/Your organization has disabled this mode/)).toBeVisible();
  expect(screen.getByRole("link", { name: "Open approval settings" })).toHaveAttribute(
    "href",
    "/orgs/org-1/members?tab=governance",
  );
  await userEvent.click(screen.getByRole("link", { name: "Open approval settings" }));
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("does not call a missing organization policy disabled or offer its settings link", async () => {
  state.orgLoaded = false;
  open();
  await userEvent.click(trigger());
  await userEvent.click(screen.getByRole("tab", { name: "Preferences" }));
  expect(screen.getByRole("radio", { name: "Approve everything" })).toBeDisabled();
  expect(screen.getByText(/Organization approval settings are not available yet/)).toBeVisible();
  expect(screen.queryByRole("link", { name: "Open approval settings" })).toBeNull();
});

it("uses an anchored panel without blocking the rest of the chat", async () => {
  open();
  await userEvent.click(trigger());
  expect(trigger()).toHaveAttribute("aria-expanded", "true");
  expect(document.querySelector("[data-radix-popper-content-wrapper]")).toBeInTheDocument();
  expect(document.body.style.pointerEvents).not.toBe("none");
});

it("offers no tools tab on the web for an agent that needs no account of the person's", async () => {
  open();
  await userEvent.click(trigger());
  expect(screen.queryByRole("tab", { name: "Tools & files" })).toBeNull();
});

it("offers the one coding account the agent codes on, under tools and not the model", async () => {
  state.personalHarness = "codex";
  open();
  await userEvent.click(trigger());
  expect(screen.queryByRole("region", { name: "Your codex account" })).toBeNull();
  await userEvent.click(screen.getByRole("tab", { name: "Tools & files" }));
  expect(screen.getByRole("region", { name: "Your codex account" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "Your claude_code account" })).toBeNull();
});

it("returns to Model when the selected agent no longer offers Tools", async () => {
  state.personalHarness = "codex";
  const view = render(<ChatControls />);
  await userEvent.click(trigger());
  await userEvent.click(screen.getByRole("tab", { name: "Tools & files" }));
  state.personalHarness = null;
  view.rerender(<ChatControls />);
  expect(screen.getByRole("tab", { name: "Model" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText(/pick a model/)).toBeVisible();
});

it("keeps both personal account connections reachable for an agent that delegates", async () => {
  open({ agentCapabilities: ["subagents"] });
  await userEvent.click(trigger());
  await userEvent.click(screen.getByRole("tab", { name: "Tools & files" }));
  expect(screen.getByRole("region", { name: "Your codex account" })).toBeVisible();
  expect(screen.getByRole("region", { name: "Your claude_code account" })).toBeVisible();
});
