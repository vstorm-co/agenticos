import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatControls } from "./chat-controls";

const state = vi.hoisted(() => ({
  profiles: [] as { id: string; label: string; provider: string; model: string }[],
  conversationId: null as string | null,
}));

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: state.profiles,
    createProfile: { mutateAsync: vi.fn(), isPending: false },
  }),
  useProviderModels: () => ({ models: [], source: "curated", isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
  useSecrets: () => ({ secrets: [] }),
}));
vi.mock("@/stores", () => ({
  useConversationStore: (pick: (state: unknown) => unknown) =>
    pick({ currentConversationId: state.conversationId }),
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
