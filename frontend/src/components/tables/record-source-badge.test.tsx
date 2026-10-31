import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecordSourceBadge } from "./record-source-badge";
vi.mock("@/components/ui", () => ({
  EntityAvatar: ({ imageSrc, name }: { imageSrc?: string; name: string }) => (
    <span data-testid="person-avatar" data-image={imageSrc}>
      {name.slice(0, 1)}
    </span>
  ),
}));
vi.mock("@/components/agents/agent-avatar", () => ({
  AgentAvatar: ({ agentId, slug }: { agentId: string; slug: string }) => (
    <span data-testid="agent-avatar" data-id={agentId} data-slug={slug} />
  ),
}));
describe("record sources", () => {
  it("uses a person's authenticated avatar and name", () => {
    render(<RecordSourceBadge source={{ kind: "user", id: "u1", name: "Jordan" }} />);
    expect(screen.getByText("Jordan")).toBeVisible();
    expect(screen.getByTestId("person-avatar")).toHaveAttribute(
      "data-image",
      "/api/users/avatar/u1",
    );
  });
  it("uses the writing agent's portrait rather than its authorizing member", () => {
    render(
      <RecordSourceBadge
        principalId="owner"
        source={{ kind: "agent", id: "a1", name: "Researcher", slug: "researcher" }}
      />,
    );
    expect(screen.getByTestId("agent-avatar")).toHaveAttribute("data-id", "a1");
    expect(screen.queryByTestId("person-avatar")).toBeNull();
  });
  it("identifies API and workflow sources without impersonating the key or workflow owner", () => {
    const { rerender } = render(
      <RecordSourceBadge
        principalId="owner"
        source={{ kind: "api", id: "k1", name: "CRM sync" }}
      />,
    );
    expect(screen.getByText("CRM sync")).toBeVisible();
    expect(screen.queryByTestId("person-avatar")).toBeNull();
    rerender(
      <RecordSourceBadge
        principalId="owner"
        source={{ kind: "workflow", id: "w1", name: "Lead intake" }}
      />,
    );
    expect(screen.getByText("Lead intake")).toBeVisible();
    expect(screen.queryByTestId("person-avatar")).toBeNull();
  });
});
