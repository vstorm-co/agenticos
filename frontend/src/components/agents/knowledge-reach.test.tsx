import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { KnowledgeReach } from "./knowledge-reach";

const { reach } = vi.hoisted(() => ({ reach: vi.fn() }));
vi.mock("@/hooks", () => ({ useKnowledgeReach: () => ({ reach: reach() }) }));

const source = (overrides: Record<string, unknown>) => ({
  kind: "skill",
  id: "s1",
  name: "ledger",
  whole_organization: false,
  groups: [],
  reaches_fewer_than_agent: false,
  ...overrides,
});

describe("KnowledgeReach", () => {
  it("is not drawn for an agent with no sources, or before it loads", () => {
    reach.mockReturnValue(null);
    const { container, rerender } = render(<KnowledgeReach agentId="a1" />);
    expect(container).toBeEmptyDOMElement();

    reach.mockReturnValue({ whole_organization: true, groups: [], sources: [] });
    rerender(<KnowledgeReach agentId="a1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("flags a Finance source on an agent the whole organization reaches", () => {
    reach.mockReturnValue({
      whole_organization: true,
      groups: [],
      sources: [
        source({ name: "ledger", groups: ["Finance"], reaches_fewer_than_agent: true }),
        source({ id: "c1", kind: "collection", name: "Handbook", whole_organization: true }),
        source({ id: "x1", kind: "context", name: "Notes" }),
      ],
    });
    render(<KnowledgeReach agentId="a1" />);

    expect(screen.getByText(/1 source is shared with fewer people/)).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
    expect(screen.getByText("shared more narrowly")).toBeInTheDocument();
    expect(screen.getAllByText("Everyone")).toHaveLength(2);
    expect(screen.getByText("Chosen people")).toBeInTheDocument();
  });

  it("raises nothing when the agent stays inside its sources' groups", () => {
    reach.mockReturnValue({
      whole_organization: false,
      groups: ["Finance"],
      sources: [source({ groups: ["Finance"] })],
    });
    render(<KnowledgeReach agentId="a1" />);

    expect(screen.queryByText(/shared with fewer people/)).toBeNull();
    expect(screen.getAllByText("Finance")).toHaveLength(2);
  });
});
