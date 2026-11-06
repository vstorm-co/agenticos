import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotificationGlyph, NotificationMeta } from "./notification-glyph";
import type { Notification } from "@/lib/notifications-api";

vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: (props: { slug: string; colorSlot?: number | null; hasAvatar?: boolean }) => (
    <span
      data-testid="face"
      data-slug={props.slug}
      data-color={String(props.colorSlot)}
      data-picture={String(props.hasAvatar)}
    />
  ),
}));

function notification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    event_type: "run_completed",
    summary: "Support's run finished.",
    context_url: null,
    read_at: null,
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

const SUPPORT = {
  id: "a1",
  slug: "support",
  name: "Support",
  has_avatar: true,
  avatar_color: 4,
};

describe("NotificationGlyph", () => {
  it("keeps the agent portrait clear of status badges", () => {
    const { container } = render(
      <NotificationGlyph item={notification({ event_type: "run_failed", agent: SUPPORT })} />,
    );

    const face = screen.getByTestId("face");
    expect(face).toHaveAttribute("data-slug", "support");
    expect(face).toHaveAttribute("data-color", "4");
    expect(face).toHaveAttribute("data-picture", "true");
    expect(container.querySelector("svg")).toBeNull();
  });

  it("draws the event's own icon for a row about no agent", () => {
    const { container } = render(
      <NotificationGlyph item={notification({ event_type: "mcp_server_recovered" })} />,
    );

    expect(screen.queryByTestId("face")).toBeNull();
    expect(container.querySelector(".lucide-plug")).not.toBeNull();
    expect(container.querySelector(".text-success")).toBeNull();
  });

  it("draws a neutral bell for a kind this console does not know yet", () => {
    const { container } = render(
      <NotificationGlyph item={notification({ event_type: "something_new", agent: null })} />,
    );

    expect(screen.queryByTestId("face")).toBeNull();
    expect(container.querySelector(".lucide-bell")).not.toBeNull();
  });
});

describe("notification event metadata", () => {
  it.each(["run_failed", "mcp_server_down", "approval_requested", "budget_warning"])(
    "keeps %s visible beside the timestamp",
    (event_type) => {
      render(<NotificationMeta item={notification({ event_type })}>5m ago</NotificationMeta>);
      expect(screen.getByText("Needs attention")).toBeInTheDocument();
      expect(screen.getByText("5m ago")).toBeInTheDocument();
    },
  );

  it.each(["run_completed", "mcp_server_recovered", "something_new"])(
    "leaves routine %s events quiet",
    (event_type) => {
      render(<NotificationMeta item={notification({ event_type })}>5m ago</NotificationMeta>);
      expect(screen.queryByText("Needs attention")).toBeNull();
      expect(screen.getByText("5m ago")).toBeInTheDocument();
    },
  );
});
