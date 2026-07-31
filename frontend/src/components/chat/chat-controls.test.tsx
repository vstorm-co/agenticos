import { fireEvent, render, screen } from "@testing-library/react";
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
  const handlers = {
    onModelProfileChange: vi.fn(),
    onTemperatureChange: vi.fn(),
    onThinkingEffortChange: vi.fn(),
    ...props,
  };
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

    const trigger = screen.getByRole("button", { name: "Chat controls" });
    expect(document.querySelector("[data-chat-settings-trigger]")).toBe(trigger);
  });

  it("says only 'Controls' until something is overridden", () => {
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

  it("says a temperature was set without saying which, on the trigger", async () => {
    const handlers = open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));

    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.3" } });

    expect(handlers.onTemperatureChange).toHaveBeenCalledWith(0.3);
    expect(screen.getByText("0.30")).toBeInTheDocument();
    expect(trigger()).toHaveTextContent("Custom");
  });

  it("shows an untouched temperature as the server's, not as a number", async () => {
    // The slider has to point somewhere; the readout is what says whether the
    // position means anything.
    open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));

    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByLabelText("Temperature")).toHaveValue("0.7");
  });

  it("gives the temperature back to the server rather than sending a number", async () => {
    const handlers = open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));
    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.3" } });

    await userEvent.click(screen.getByRole("button", { name: /Reset to server default/ }));

    expect(handlers.onTemperatureChange).toHaveBeenLastCalledWith(null);
    expect(screen.getByText("default")).toBeInTheDocument();
  });

  it("offers no reset for a temperature nobody set", async () => {
    open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));

    expect(screen.queryByRole("button", { name: /Reset to server default/ })).toBeNull();
  });

  it("sends the thinking effort that was chosen, and 'off' as no override", async () => {
    // `off` is the absence of a setting rather than a value: a model that reasons
    // by default must not be told to stop.
    const handlers = open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));

    await userEvent.click(screen.getByRole("button", { name: "High" }));
    expect(handlers.onThinkingEffortChange).toHaveBeenCalledWith("high");
    expect(trigger()).toHaveTextContent("Custom");

    await userEvent.click(screen.getByRole("button", { name: "Off" }));
    expect(handlers.onThinkingEffortChange).toHaveBeenLastCalledWith(null);
    expect(trigger()).toHaveTextContent("Controls");
  });

  it("explains what the chosen effort means", async () => {
    open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(screen.getByText("Direct answer, no reasoning")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Low" }));

    expect(screen.getByText("Quick reasoning")).toBeInTheDocument();
    expect(screen.queryByText("Direct answer, no reasoning")).toBeNull();
  });

  it("shows both overrides on the trigger at once", async () => {
    const handlers = open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /pick a model/ }));
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));
    await userEvent.click(screen.getByRole("button", { name: "High" }));

    expect(trigger()).toHaveTextContent("openai default · Custom");
    expect(handlers.onModelProfileChange).toHaveBeenCalled();
  });

  it("goes back to the model tab", async () => {
    // Both tabs are reachable in both directions; the popover stays open across
    // the switch so a comparison does not cost two openings.
    open();
    await userEvent.click(trigger());
    await userEvent.click(screen.getByRole("button", { name: /Settings/ }));
    expect(screen.getByLabelText("Temperature")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Model/ }));

    expect(screen.getByRole("button", { name: /pick a model/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Temperature")).toBeNull();
  });

  it("offers only the tabs the caller can handle", async () => {
    // The same popover is mounted where only one of the two is wired up.
    render(<ChatControls onModelProfileChange={vi.fn()} />);
    await userEvent.click(trigger());

    expect(screen.getByRole("button", { name: /Model/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Settings/ })).toBeNull();
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
