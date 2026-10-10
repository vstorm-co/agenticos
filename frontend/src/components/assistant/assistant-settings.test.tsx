import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantState } from "@/types/assistant";

import { AssistantSettings } from "./assistant-settings";

const state = vi.hoisted(() => ({
  assistant: null as AssistantState | null,
  isLoading: false,
  mutate: vi.fn(),
  isPending: false,
  permissions: new Set<string>(),
}));

vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({ assistant: state.assistant, isLoading: state.isLoading }),
  useUpdateAssistant: () => ({ mutate: state.mutate, isPending: state.isPending }),
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (perm: string) => state.permissions.has(perm) }),
  useModelProviders: () => ({ profiles: [], profilesStatus: "loaded" }),
}));
// The picker is tested on its own; here it only has to report a choice.
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    value,
    allowAdd,
    onChange,
  }: {
    value: string | null;
    allowAdd: boolean;
    onChange: (id: string) => void;
  }) => (
    <button type="button" data-allow-add={String(allowAdd)} onClick={() => onChange("m2")}>
      picker:{value ?? "none"}
    </button>
  ),
}));

function assistant(overrides: Partial<AssistantState> = {}): AssistantState {
  return {
    status: "ready",
    agent_id: "a1",
    slug: "ai-architect",
    name: "AI Architect",
    greeting: null,
    avatar_url: null,
    avatar_color: null,
    model_profile_id: "m1",
    collection_ids: [],
    can_use: true,
    can_configure: true,
    ...overrides,
  };
}

beforeEach(() => {
  state.assistant = assistant();
  state.isLoading = false;
  state.isPending = false;
  state.mutate.mockReset();
  state.permissions = new Set(["connections:manage"]);
});

afterEach(() => localStorage.clear());

describe("Settings → Assistant", () => {
  it("waits for the assistant before drawing anything", () => {
    state.isLoading = true;
    render(<AssistantSettings />);

    expect(screen.queryByText("Your tips")).toBeNull();
  });

  it("draws nothing when there is no assistant to read", () => {
    state.assistant = null;
    const { container } = render(<AssistantSettings />);

    expect(container).toBeEmptyDOMElement();
  });

  it("tells somebody without agents:run why there is no assistant, and nothing more", () => {
    state.assistant = assistant({ can_use: false, can_configure: false });
    render(<AssistantSettings />);

    expect(screen.getByText(/Your role doesn't include running agents/)).toBeInTheDocument();
    expect(screen.queryByText("Your tips")).toBeNull();
    expect(screen.queryByText("For the organization")).toBeNull();
  });

  it("lets a member switch their tips off and bring silenced pages back", () => {
    state.assistant = assistant({ can_configure: false });
    localStorage.setItem(
      "assistant-bubbles",
      JSON.stringify({ silenced: ["/agents"], off: false }),
    );
    render(<AssistantSettings />);

    expect(screen.queryByText("For the organization")).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Show tips in speech bubbles" }));
    expect(JSON.parse(localStorage.getItem("assistant-bubbles")!)).toMatchObject({ off: true });

    fireEvent.click(
      screen.getByRole("button", { name: "Show tips again on the 1 page I silenced" }),
    );
    expect(JSON.parse(localStorage.getItem("assistant-bubbles")!)).toEqual({
      silenced: [],
      off: true,
    });
    expect(screen.queryByRole("button", { name: /Show tips again/ })).toBeNull();
  });

  it("saves an administrator's name and greeting, trimmed, and an empty greeting as none", () => {
    state.assistant = assistant({ greeting: "Hello" });
    render(<AssistantSettings />);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  Ola z IT " } });
    fireEvent.change(screen.getByLabelText("Greeting"), { target: { value: "   " } });
    fireEvent.click(save);

    expect(state.mutate).toHaveBeenCalledWith({ name: "Ola z IT", greeting: null });
  });

  it("refuses an empty name", () => {
    render(<AssistantSettings />);

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  " } });

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("switches it off and picks its model straight away", () => {
    render(<AssistantSettings />);

    fireEvent.click(screen.getByRole("switch", { name: "Assistant switched on" }));
    expect(state.mutate).toHaveBeenCalledWith({ enabled: false });

    fireEvent.click(screen.getByRole("button", { name: "picker:m1" }));
    expect(state.mutate).toHaveBeenCalledWith({ model_profile_id: "m2" });
  });

  it("says a model is missing, and offers adding one only to who may", () => {
    state.assistant = assistant({ status: "needs_model", model_profile_id: null });
    state.permissions = new Set();
    render(<AssistantSettings />);

    expect(screen.getByText(/It has no model yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "picker:none" })).toHaveAttribute(
      "data-allow-add",
      "false",
    );
  });

  it("shows a switched-off assistant as off", () => {
    state.assistant = assistant({ status: "disabled", greeting: "Hej" });
    render(<AssistantSettings />);

    expect(screen.getByRole("switch", { name: "Assistant switched on" })).not.toBeChecked();
    expect(screen.getByLabelText("Greeting")).toHaveValue("Hej");
  });
});
