import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ValidationProblem } from "@/components/workflows/validation";

import {
  fieldErrors,
  nodeLevelProblems,
  nodeProblemCount,
  ProblemsFooter,
  WarningBadge,
} from "./problems";

function problem(over: Partial<ValidationProblem>): ValidationProblem {
  return { nodeId: null, edgeId: null, field: null, code: "x", message: "msg", ...over };
}

const problems: ValidationProblem[] = [
  problem({ nodeId: "N", field: "a", message: "A bad", code: "c1" }),
  problem({ nodeId: "N", field: "a", message: "A second", code: "c2" }),
  problem({ nodeId: "N", field: null, message: "Node bad", code: "c3" }),
  problem({ nodeId: "M", field: "b", message: "Other node", code: "c4" }),
  problem({ nodeId: null, field: null, message: "Graph bad", code: "c5" }),
];

describe("problem selectors", () => {
  it("keeps the first message per field for one node", () => {
    const map = fieldErrors(problems, "N");
    expect(map.get("a")).toBe("A bad");
    expect(map.size).toBe(1);
  });

  it("collects a node's node-level problems", () => {
    expect(nodeLevelProblems(problems, "N").map((p) => p.message)).toEqual(["Node bad"]);
  });

  it("counts every problem for a node", () => {
    expect(nodeProblemCount(problems, "N")).toBe(3);
    expect(nodeProblemCount(problems, "M")).toBe(1);
  });
});

describe("WarningBadge", () => {
  it("renders a pluralised count", () => {
    render(<WarningBadge count={3} />);
    expect(screen.getByLabelText("3 problems")).toBeVisible();
  });

  it("renders the singular form", () => {
    render(<WarningBadge count={1} />);
    expect(screen.getByLabelText("1 problem")).toBeVisible();
  });

  it("renders nothing when clean", () => {
    const { container } = render(<WarningBadge count={0} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ProblemsFooter", () => {
  it("renders nothing when there are no problems", () => {
    const { container } = render(<ProblemsFooter problems={[]} onSelectNode={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("expands, links a node problem and skips a graph-level one", async () => {
    const onSelectNode = vi.fn();
    render(<ProblemsFooter problems={problems} onSelectNode={onSelectNode} />);
    // Collapsed by default.
    expect(screen.queryByText("A bad")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "5 problems" }));
    await userEvent.click(screen.getByRole("button", { name: "A bad" }));
    expect(onSelectNode).toHaveBeenCalledWith("N");
    // The graph-level problem has no link, just text.
    expect(screen.getByText("Graph bad")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Graph bad" })).toBeNull();
    // Collapse again.
    await userEvent.click(screen.getByRole("button", { name: "5 problems" }));
    expect(screen.queryByText("A bad")).toBeNull();
  });
});
