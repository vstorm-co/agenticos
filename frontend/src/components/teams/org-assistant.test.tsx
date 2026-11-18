import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

    fireEvent.click(screen.getByRole("button", { name: "AI Architect" }));
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

  it("shows the switched-off assistant without a greeting editor", () => {
    state.assistant = assistant({ status: "disabled", greeting: "Hej" });
    render(<OrgAssistant orgId="o1" />);

    expect(screen.getByRole("switch", { name: "Switched on" })).not.toBeChecked();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("keeps the switch separate from its keyboard-operated disclosure and preserves the Builder link", async () => {
    render(<OrgAssistant orgId="o1" />);
    const heading = screen.getByRole("button", { name: "AI Architect" });
    expect(heading).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("switch", { name: "Switched on" })).toBeVisible();
    await userEvent.click(screen.getByRole("switch", { name: "Switched on" }));
    expect(heading).toHaveAttribute("aria-expanded", "false");
    expect(state.mutate).toHaveBeenCalledWith({ enabled: false });
    heading.focus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("link", { name: "Open in Agent Builder" })).toBeVisible();
    await userEvent.keyboard(" ");
    expect(heading).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Open in Agent Builder" })).not.toBeInTheDocument();
  });

  it("says where to give it a model when it has none", () => {
    state.assistant = assistant({ status: "needs_model" });
    render(<OrgAssistant orgId="o1" />);

    expect(screen.getByText(/It has no model yet/)).toBeInTheDocument();
  });
});
