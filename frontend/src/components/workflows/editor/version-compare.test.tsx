import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  edge,
  graph,
  makeDefinition,
  node,
  port,
} from "@/components/workflows/validation/fixtures";

import { VersionComparison } from "./version-compare";

const STEP = makeDefinition({
  id: "test.step",
  name: "Test step",
  ports: [port("in", "input", null), port("out", "output", null)],
});
const CATALOG = [STEP];

describe("VersionComparison", () => {
  it("marks each step on the canvas and lists what changed in it", () => {
    const version = graph({
      entry: "a",
      nodes: [node("a", "test.step", { message: "hi" }), node("gone", "test.step")],
      edges: [edge("e1", "a", "out", "gone", "in")],
    });
    const draft = graph({
      entry: "a",
      nodes: [
        node("a", "test.step", { message: "hello" }),
        { ...node("new", "test.step"), label: "Tell sales" },
      ],
      edges: [edge("e2", "a", "out", "new", "in")],
    });
    render(<VersionComparison version={version} draft={draft} catalog={CATALOG} />);

    const list = screen.getByRole("complementary", { name: "What changed" });
    expect(
      within(list).getByText("3 steps differ; 1 connection added, 1 removed."),
    ).toBeInTheDocument();
    expect(within(list).getByText("Tell sales")).toBeInTheDocument();
    expect(within(list).getByText("Setting message")).toBeInTheDocument();
    for (const mark of ["Added", "Changed", "Removed"]) {
      expect(screen.getAllByText(mark).length).toBeGreaterThanOrEqual(2);
    }
  });

  it("says when the draft is the same as the version", () => {
    const same = graph({ entry: "a", nodes: [node("a", "test.step")] });
    render(<VersionComparison version={same} draft={same} catalog={CATALOG} />);
    expect(screen.getByText("The draft is the same as this version.")).toBeInTheDocument();
  });

  it("names a step the catalog does not know by its kind", () => {
    const version = graph({ entry: "a", nodes: [node("a", "test.step")] });
    const draft = graph({ entry: "a", nodes: [node("a", "test.step"), node("x", "future.step")] });
    render(<VersionComparison version={version} draft={draft} catalog={CATALOG} />);
    expect(
      within(screen.getByRole("complementary", { name: "What changed" })).getByText("future.step"),
    ).toBeInTheDocument();
  });
});
