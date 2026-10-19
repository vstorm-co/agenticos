import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AssistantState } from "@/types/assistant";

import { OrgAssistant } from "./org-assistant";

const state = vi.hoisted(() => ({
  assistant: null as AssistantState | null,
  activeOrgId: "o1" as string | null,
  mutate: vi.fn(),
  isPending: false,
}));

vi.mock("@/hooks/use-assistant", () => ({
  useAssistant: () => ({ assistant: state.assistant }),
  useUpdateAssistant: () => ({ mutate: state.mutate, isPending: state.isPending }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (pick: (store: { activeOrgId: string | null }) => unknown) =>
    pick({ activeOrgId: state.activeOrgId }),
}));

function assistant(overrides: Partial<AssistantState> = {}): AssistantState {
  return {
    status: "ready",
    agent_id: "a1",
    slug: "ai-architect",
    name: "Architect",
    named_by_default: true,
    greeting: null,
    avatar_url: null,
    avatar_color: null,
    wears_mark: true,
    can_use: true,
    can_configure: true,
    ...overrides,
  };
}

beforeEach(() => {
  state.assistant = assistant();
  state.activeOrgId = "o1";
  state.isPending = false;
  state.mutate.mockReset();
});

describe("OrgAssistant", () => {
  it("draws nothing for somebody who may not change it", () => {
    state.assistant = assistant({ can_configure: false });
    const { container } = render(<OrgAssistant orgId="o1" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing on another organization's page, which `/assistant` does not answer for", () => {
    const { container } = render(<OrgAssistant orgId="o2" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("draws nothing before there is an assistant to change", () => {
    state.assistant = null;
    const { container } = render(<OrgAssistant orgId="o1" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("links the agent itself to the Builder", () => {
    render(<OrgAssistant orgId="o1" />);

    expect(screen.getByRole("link", { name: "Open in Agent Builder" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
  });

  it("switches it off at once", () => {
    render(<OrgAssistant orgId="o1" />);

    fireEvent.click(screen.getByRole("switch", { name: "Switched on" }));

    expect(state.mutate).toHaveBeenCalledWith({ enabled: false });
  });

  it("shows a switched-off assistant as off, with its greeting", () => {
    state.assistant = assistant({ status: "disabled", greeting: "Hej" });
    render(<OrgAssistant orgId="o1" />);

    expect(screen.getByRole("switch", { name: "Switched on" })).not.toBeChecked();
    expect(screen.getByLabelText("Greeting")).toHaveValue("Hej");
  });

  it("saves a greeting trimmed, an empty one as none, and only once it changed", () => {
    state.assistant = assistant({ greeting: "Hello" });
    render(<OrgAssistant orgId="o1" />);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Greeting"), { target: { value: "   " } });
    fireEvent.click(save);

    expect(state.mutate).toHaveBeenCalledWith({ greeting: null });
  });

  it("says where to give it a model when it has none", () => {
    state.assistant = assistant({ status: "needs_model" });
    render(<OrgAssistant orgId="o1" />);

    expect(screen.getByText(/It has no model yet/)).toBeInTheDocument();
  });
});
