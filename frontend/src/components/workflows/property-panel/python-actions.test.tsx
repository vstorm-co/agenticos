import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeCatalog, makeDefinition } from "@/components/workflows/validation/fixtures";

import { PythonActionsGuide } from "./python-actions";

const catalog = makeCatalog([
  makeDefinition({
    id: "mcp.call",
    python_callable: true,
    input_schema: { type: "object", properties: { arguments: { type: "object" } } },
  }),
]);

describe("PythonActionsGuide", () => {
  it("explains an unbound step without inventing callable functions or input keys", () => {
    render(
      <PythonActionsGuide
        catalog={catalog}
        value={{ gone: { type: "old.action" } }}
        argKeys={[]}
      />,
    );
    expect(
      screen.getByText("Input · Read mapped values from args: no input fields mapped yet"),
    ).toBeVisible();
    expect(
      screen.getByText("Functions · Add an action below to make its function available here."),
    ).toBeVisible();
    expect(
      screen.getByText("Output · The last expression becomes this step’s result."),
    ).toBeVisible();
    const help = screen.getByText("How to write this step").closest("details");
    expect(help).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("How to write this step"));
    expect(screen.getByText("result = args result")).toBeVisible();
  });

  it("shows actual input keys and only currently available function bindings", () => {
    render(
      <PythonActionsGuide
        catalog={catalog}
        value={{ lookup: { type: "mcp.call" }, missing: { type: "old.action" } }}
        argKeys={["host", "limit"]}
      />,
    );
    expect(screen.getByText("Input · Read mapped values from args: host, limit")).toBeVisible();
    expect(screen.getByText("Functions · Call lookup with named arguments.")).toBeVisible();
    fireEvent.click(screen.getByText("How to write this step"));
    expect(screen.getByText("result = lookup(arguments=...) result")).toBeVisible();
    expect(screen.getByText(/Replace each \.\.\. with an input value/)).toBeVisible();
  });
});
