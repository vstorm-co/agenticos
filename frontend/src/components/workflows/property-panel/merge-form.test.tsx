import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  edge,
  echo,
  graph,
  makeCatalog,
  makeDefinition,
  node,
  port,
} from "@/components/workflows/validation/fixtures";
import type { NodeInstance } from "@/lib/workflows/types";

import { MergeForm } from "./merge-form";

const IN = port("in", "input", null);
const OUT = port("out", "output", null);
const CATALOG = makeCatalog([
  makeDefinition({ id: "debug.echo", name: "Echo", ports: [IN, OUT] }),
  makeDefinition({ id: "logic.split", name: "Split", kind: "control", ports: [IN] }),
  makeDefinition({ id: "logic.merge", name: "Merge", kind: "control", ports: [IN, OUT] }),
]);

function setup(
  config: Record<string, unknown>,
  options: { disabled?: boolean; split?: boolean } = {},
) {
  const merge = node("J", "logic.merge", config);
  const source: NodeInstance[] = options.split
    ? [node("S", "logic.split", { branches: [{ name: "left" }, { name: "right" }] })]
    : [];
  const g = options.split
    ? graph({
        entry: "S",
        nodes: [...source, merge],
        edges: [edge("e0", "S", "left", "J", "in"), edge("e1", "S", "right", "J", "in")],
      })
    : graph({
        entry: "A",
        nodes: [{ ...echo("A"), label: "Research" }, echo("B"), merge],
        edges: [edge("e0", "A", "out", "J", "in"), edge("e1", "B", "out", "J", "in")],
      });
  const update = vi.fn();
  render(
    <MergeForm
      node={merge}
      graph={g}
      catalog={CATALOG}
      disabled={options.disabled}
      updateNodeConfig={update}
    />,
  );
  return update;
}

describe("MergeForm", () => {
  it("shows an unconfigured merge as waiting for the branch that ran", () => {
    setup({});
    expect(screen.getByLabelText("The branch that ran")).toBeChecked();
    expect(screen.getByLabelText("All branches")).not.toBeChecked();
    expect(screen.queryByLabelText(/Branch name/)).toBeNull();
  });

  it("writes the mode with every branch's name when it switches to all branches", () => {
    const update = setup({});
    fireEvent.click(screen.getByLabelText("All branches"));
    expect(update).toHaveBeenCalledWith("J", {
      wait_for: "all",
      branch_keys: [
        { source_node_id: "A", source_port: "out", key: "research" },
        { source_node_id: "B", source_port: "out", key: "echo" },
      ],
    });
  });

  it("switches back to the branch that ran", () => {
    const update = setup({ wait_for: "all", branch_keys: [] });
    fireEvent.click(screen.getByLabelText("The branch that ran"));
    expect(update).toHaveBeenCalledWith("J", { wait_for: "one", branch_keys: [] });
  });

  it("names each branch after its step, and a split's branch after the split", () => {
    setup({ wait_for: "all" });
    expect(screen.getByLabelText(/Branch name · Research/)).toHaveValue("research");
  });

  it("shows a split's branches with their ports", () => {
    setup({ wait_for: "all" }, { split: true });
    expect(screen.getByLabelText(/Branch name · .*Split.* · left/)).toHaveValue("left");
    expect(screen.getByLabelText(/Branch name · .*Split.* · right/)).toHaveValue("right");
  });

  it("writes every name when one is changed", () => {
    const update = setup(
      {
        wait_for: "all",
        branch_keys: [{ source_node_id: "A", source_port: "out", key: "research" }],
      },
      {},
    );
    fireEvent.change(screen.getByLabelText(/Branch name · Research/), {
      target: { value: "sources" },
    });
    const written = update.mock.calls[0]?.[1] as { branch_keys: { key: string }[] };
    expect(written.branch_keys.map((entry) => entry.key)).toEqual(["sources", expect.any(String)]);
  });

  it("names a branch whose step has no definition in the catalog after its definition id", () => {
    const merge = node("J", "logic.merge", { wait_for: "all" });
    const g = graph({
      entry: "G",
      nodes: [node("G", "gone.step", {}), echo("B"), merge],
      edges: [edge("e0", "G", "out", "J", "in"), edge("e1", "B", "out", "J", "in")],
    });
    render(<MergeForm node={merge} graph={g} catalog={CATALOG} updateNodeConfig={vi.fn()} />);
    expect(screen.getByLabelText(/Branch name · gone\.step/)).toBeInTheDocument();
  });

  it("cannot be changed when it is read-only", () => {
    setup({ wait_for: "all" }, { disabled: true });
    expect(screen.getByLabelText("The branch that ran")).toBeDisabled();
    expect(screen.getByLabelText(/Branch name · Research/)).toBeDisabled();
  });
});
