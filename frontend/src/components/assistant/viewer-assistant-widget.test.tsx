import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ViewerAssistantWidget, viewerChatAgentId } from "./viewer-assistant-widget";

const state = vi.hoisted(() => ({
  pathname: "/apps/app-1",
  artifact: { agent_id: "publisher" as string | null },
  agents: [] as { id: string; status: string; can_run: boolean }[],
  assistantDefault: "missing",
  artifactLoading: false,
  agentsLoading: false,
}));

vi.mock("@/lib/locale-navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "app-1" }) }));
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifact: () => ({ artifact: state.artifact, isLoading: state.artifactLoading }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents: state.agents, isLoading: state.agentsLoading }),
}));
vi.mock("./assistant-widget", () => ({
  AssistantWidget: ({
    defaultAgentId,
    viewer,
  }: {
    defaultAgentId?: string | null;
    viewer?: boolean;
  }) => (
    <div
      data-testid="assistant"
      data-default-agent={defaultAgentId ?? state.assistantDefault}
      data-viewer={viewer}
    />
  ),
}));

describe("viewer assistant launcher", () => {
  beforeEach(() => {
    state.pathname = "/apps/app-1";
    state.artifact = { agent_id: "publisher" };
    state.agents = [{ id: "publisher", status: "published", can_run: true }];
    state.artifactLoading = false;
    state.agentsLoading = false;
  });

  it("starts with the publishing agent when it is runnable", () => {
    render(<ViewerAssistantWidget />);
    expect(screen.getByTestId("assistant")).toHaveAttribute("data-default-agent", "publisher");
    expect(screen.getByTestId("assistant")).toHaveAttribute("data-viewer", "true");
  });

  it.each([
    { reason: "unpublished", agent: { id: "publisher", status: "draft", can_run: true } },
    { reason: "not runnable", agent: { id: "publisher", status: "published", can_run: false } },
  ])("falls back to the organization assistant when the publisher is $reason", ({ agent }) => {
    state.agents = [agent];
    render(<ViewerAssistantWidget />);
    expect(screen.getByTestId("assistant")).toHaveAttribute("data-default-agent", "missing");
  });

  it("does not look up an app for another viewer page", () => {
    state.pathname = "/oauth/consent";
    render(<ViewerAssistantWidget />);
    expect(screen.queryByTestId("assistant")).not.toBeInTheDocument();
  });

  it.each(["artifactLoading", "agentsLoading"] as const)(
    "waits for %s before offering the publishing agent",
    (pending) => {
      state[pending] = true;
      const view = render(<ViewerAssistantWidget />);
      expect(screen.queryByTestId("assistant")).not.toBeInTheDocument();

      state[pending] = false;
      view.rerender(<ViewerAssistantWidget />);
      expect(screen.getByTestId("assistant")).toHaveAttribute("data-default-agent", "publisher");
    },
  );
});

describe("viewerChatAgentId", () => {
  it("requires a published agent that the current member can run", () => {
    expect(
      viewerChatAgentId(
        "publisher",
        [{ id: "publisher", status: "published", can_run: true }],
        "assistant",
      ),
    ).toBe("publisher");
    expect(
      viewerChatAgentId(
        "publisher",
        [{ id: "publisher", status: "published", can_run: false }],
        "assistant",
      ),
    ).toBe("assistant");
    expect(viewerChatAgentId(null, [], "assistant")).toBe("assistant");
  });
});
