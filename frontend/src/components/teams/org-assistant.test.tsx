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

  it("keeps the organization card focused on availability without a Builder CTA", () => {
    render(<OrgAssistant orgId="o1" />);

    expect(screen.queryByRole("link", { name: "Open in Agent Builder" })).toBeNull();
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

  it("keeps availability independently editable without navigation", async () => {
    render(<OrgAssistant orgId="o1" />);
    expect(screen.getByRole("heading", { name: "AI Architect" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "AI Architect" })).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Switched on" }));
    expect(state.mutate).toHaveBeenCalledWith({ enabled: false });
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("blocks another toggle while its write is pending", async () => {
    state.isPending = true;
    render(<OrgAssistant orgId="o1" />);
    const toggle = screen.getByRole("switch", { name: "Switched on" });
    expect(toggle).toBeDisabled();
    await userEvent.click(toggle);
    expect(state.mutate).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Open in Agent Builder" })).toBeNull();
  });

  it("says where to give it a model when it has none", () => {
    state.assistant = assistant({ status: "needs_model" });
    render(<OrgAssistant orgId="o1" />);

    expect(screen.getByText(/It has no model yet/)).toBeInTheDocument();
  });
});
