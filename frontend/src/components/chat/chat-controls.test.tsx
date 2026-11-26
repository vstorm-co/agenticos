import { useChatControlsStore } from "@/stores/chat-controls-store";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkOnStore } from "@/stores/work-on-store";
import { ChatControls } from "./chat-controls";
import { ChatLayout } from "./chat-layout";

const state = vi.hoisted(() => ({
  desktop: false,
  personalModel: false,
  profiles: [] as {
    id: string;
    label: string;
    provider: string;
    model: string;
    chat_capable?: boolean;
    missing_key?: boolean;
  }[],
  publishedModel: null as { provider: string; model: string; label: string } | null,
  catalog: [] as { id: string; name: string }[],
  conversationId: null as string | null,
  // Both halves of "may this session waive approvals": the caller's permission
  // and the organization's ceiling (#925).
  mayDecide: true,
  permissionsLoading: false,
  orgAllowsWaiving: true,
  orgLoaded: true,
  pathname: "/chat",
  query: "",
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
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useSearchParams: () => new URLSearchParams(state.query),
}));
vi.mock("@/stores/onboarding-store", () => ({
  useOnboardingStore: (pick: (store: unknown) => unknown) => pick({ openPage: state.openPage }),
}));

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: state.profiles,
    catalog: [{ id: "openai_codex", name: "ChatGPT (Codex)" }],
    createProfile: { mutateAsync: vi.fn(), isPending: false },
  }),
  useProviderModels: () => ({
    models: state.catalog,
    refused: [],
    source: "curated",
    isLoading: false,
  }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
  useSecrets: () => ({ secrets: [] }),
  usePermissions: () => ({ can: () => state.mayDecide, isLoading: state.permissionsLoading }),
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
vi.mock("@/hooks/use-subscription-accounts", () => ({
  useSubscriptionAccounts: () => ({ accounts: { data: { items: [] } } }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "agent-1",
        personal_coding_harness: state.personalHarness,
        personal_model_key: state.personalModel,
        published_model: state.publishedModel,
      },
    ],
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
    presentation,
  }: {
    presentation?: string;
    value: string | null;
    onChange: (next: string | null) => void;
  }) => (
    <button type="button" data-presentation={presentation} onClick={() => onChange("p-1")}>
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
  state.publishedModel = null;
  state.catalog = [];
  state.desktop = false;
  state.personalModel = false;
  useWorkOnStore.setState({ byConversation: {}, draft: null, draftProjectKey: null });
  state.profiles = [{ id: "p-1", label: "openai default", provider: "openai", model: "gpt-4.1" }];
  state.conversationId = null;
  state.mayDecide = true;
  state.permissionsLoading = false;
  state.orgAllowsWaiving = true;
  state.orgLoaded = true;
  state.pathname = "/chat";
  state.query = "";
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
    const askHint = "Ask before every tool call.";
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

it("offers both personal coding accounts under tools, with neither in the model tab", async () => {
  state.personalHarness = "codex";
  open();
  await userEvent.click(trigger());
  expect(screen.queryByRole("region", { name: "Your codex account" })).toBeNull();
  await userEvent.click(screen.getByRole("tab", { name: "Tools & files" }));
  expect(screen.getByRole("region", { name: "Your codex account" })).toBeVisible();
  expect(screen.getByRole("region", { name: "Your claude_code account" })).toBeVisible();
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

it("keeps usage inside the controls panel", async () => {
  render(<ChatControls usageSlot={<span>Context usage details</span>} />);
  expect(screen.queryByText("Context usage details")).toBeNull();
  await userEvent.click(trigger());
  expect(screen.getByText("Context usage details")).toBeVisible();
});

vi.mock("./personal-model-connection", () => ({
  PersonalModelConnection: () => <p>Private model connection form</p>,
}));
it("offers the private connection instead of a model picker for a fixed personal-key agent", async () => {
  state.personalModel = true;
  open();
  await userEvent.click(trigger());
  expect(screen.getByText("Private model connection form")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /pick a model/ })).not.toBeInTheDocument();
});

it("clears a saved model override when switching to a personal-key agent", async () => {
  const changed = vi.fn();
  const { rerender } = render(<ChatControls onModelProfileChange={changed} />);
  await userEvent.click(trigger());
  await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));
  expect(changed).toHaveBeenLastCalledWith("p-1");
  state.personalModel = true;
  rerender(<ChatControls onModelProfileChange={changed} />);
  expect(changed).toHaveBeenLastCalledWith(null);
});

describe("main chat composition", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("names the active model and provider without repeating the saved profile label", () => {
    state.publishedModel = {
      provider: "openai_codex",
      model: "gpt-6.2-astra",
      label: "ChatGPT (Codex subscription) · gpt-6.2-astra",
    };
    state.catalog = [{ id: "gpt-6.2-astra", name: "GPT-6.2 Astra" }];

    const { rerender } = render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    const control = screen.getByRole("button", { name: "Model" });
    expect(control).toHaveTextContent(/^GPT-6.2 Astra ChatGPT \(Codex\)$/);
    expect(control).toHaveAccessibleDescription("GPT-6.2 Astra ChatGPT (Codex)");

    state.catalog = [];
    rerender(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    expect(control).toHaveTextContent(/^gpt-6.2-astra ChatGPT \(Codex\)$/);
    expect(control).toHaveAttribute("title", "gpt-6.2-astra · ChatGPT (Codex)");
  });

  it("offers one model control without repeated permission choices", async () => {
    vi.stubEnv("NODE_ENV", "development");
    render(
      <ChatLayout>
        <ChatControls />
        <ChatControls settingsOnly />
      </ChatLayout>,
    );
    expect(screen.getAllByRole("button", { name: "Model" })).toHaveLength(1);
    await userEvent.click(trigger());
    expect(screen.getByRole("dialog", { name: "Chat controls" })).toBeVisible();
    expect(screen.queryByRole("group", { name: "Permissions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Model" })).not.toBeInTheDocument();
  });

  it("does not add a design switcher to the chat", () => {
    vi.stubEnv("NODE_ENV", "development");
    render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    expect(screen.queryByRole("navigation", { name: "Chat design previews" })).toBeNull();
    expect(screen.getByRole("button", { name: "Model" })).toBeVisible();
  });

  it("keeps actual context usage directly reachable outside the settings popover", () => {
    vi.stubEnv("NODE_ENV", "development");
    render(
      <ChatLayout>
        <ChatControls usageSlot={<button type="button">Current context usage</button>} />
      </ChatLayout>,
    );
    expect(screen.getByRole("button", { name: "Current context usage" })).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("puts context usage immediately before the model in Minimal", () => {
    vi.stubEnv("NODE_ENV", "development");
    render(
      <ChatLayout>
        <ChatControls usageSlot={<button type="button">Current context usage</button>} />
      </ChatLayout>,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.indexOf(screen.getByRole("button", { name: "Current context usage" }))).toBe(
      buttons.indexOf(screen.getByRole("button", { name: "Model" })) - 1,
    );
  });

  it("keeps the model arrow tied to the open state", async () => {
    vi.stubEnv("NODE_ENV", "development");
    render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    const model = screen.getByRole("button", { name: "Model" });
    expect(model).toHaveAttribute("data-state", "closed");
    expect(model.querySelector("svg.lucide-chevron-down")).toHaveClass(
      "group-data-[state=open]/model:rotate-180",
    );
    await userEvent.click(model);
    expect(model).toHaveAttribute("data-state", "open");
    await userEvent.keyboard("{Escape}");
    expect(model).toHaveAttribute("data-state", "closed");
  });

  it("leaves the account palette unchanged in the main chat", () => {
    vi.stubEnv("NODE_ENV", "development");
    const view = render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    expect(document.documentElement).not.toHaveAttribute("data-chat-preview");
    view.unmount();
    expect(document.documentElement).not.toHaveAttribute("data-chat-preview");
  });

  it("delegates main-chat model selection to the provider library", async () => {
    vi.stubEnv("NODE_ENV", "development");
    state.profiles.push(
      {
        id: "image",
        label: "Image only",
        provider: "openai",
        model: "image-model",
        chat_capable: false,
      },
      {
        id: "keyless",
        label: "Missing key",
        provider: "openai",
        model: "chat-model",
        missing_key: true,
      },
    );
    render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    expect(screen.getByRole("button", { name: /pick a model/ })).toHaveAttribute(
      "data-presentation",
      "library",
    );
  });

  it("keeps model inspection reachable while the picker owns permission checks", async () => {
    vi.stubEnv("NODE_ENV", "development");
    state.mayDecide = false;
    render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    expect(screen.getByRole("button", { name: /pick a model/ })).toHaveAttribute(
      "data-presentation",
      "library",
    );
  });

  it("keeps the library's panel while the initial permissions load", async () => {
    state.permissionsLoading = true;
    state.mayDecide = false;
    const chat = (
      <ChatLayout>
        <ChatControls />
      </ChatLayout>
    );
    const { rerender } = render(chat);
    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    const panel = screen.getByRole("dialog", { name: "Model" });
    const size = "h-[min(29rem,var(--radix-popover-content-available-height,29rem))]";
    expect(panel).toHaveClass(size);
    expect(panel.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.queryByRole("button", { name: /pick a model/ })).toBeNull();

    state.permissionsLoading = false;
    state.mayDecide = true;
    rerender(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    expect(screen.getByRole("dialog", { name: "Model" })).toBe(panel);
    expect(panel).toHaveClass(size);
    expect(screen.getByRole("button", { name: /pick a model/ })).toBeVisible();
  });

  it("saves model overrides through the existing scoped controls", async () => {
    vi.stubEnv("NODE_ENV", "development");
    const changed = vi.fn();
    render(
      <ChatLayout>
        <ChatControls onModelProfileChange={changed} />
      </ChatLayout>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));
    expect(changed).toHaveBeenCalledWith("p-1");
  });

  it("keeps personal model connections separate from organization overrides", async () => {
    vi.stubEnv("NODE_ENV", "development");
    state.personalModel = true;
    render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    expect(screen.getByText("Private model connection form")).toBeVisible();
    expect(screen.queryByRole("button", { name: /pick a model/ })).not.toBeInTheDocument();
  });

  it("uses the selected composition in production without experimental flags", () => {
    vi.stubEnv("NODE_ENV", "production");
    render(
      <ChatLayout>
        <ChatControls />
      </ChatLayout>,
    );
    expect(document.querySelector("[data-chat-layout]")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Model" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Model" })).toBeNull();
  });
});
