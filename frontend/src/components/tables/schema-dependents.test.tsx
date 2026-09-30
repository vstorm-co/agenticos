import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api-client";

import { SchemaDependents } from "./schema-dependents";

function refusal(dependents: unknown[]) {
  return new ApiError(409, "Other resources depend on this and must be changed first", {
    error: {
      code: "SCHEMA_DEPENDENCY",
      message: "Other resources depend on this and must be changed first",
      details: { dependents },
    },
  });
}

function renderWith(error: unknown) {
  return render(<SchemaDependents error={error} />);
}

describe("SchemaDependents", () => {
  it("names each kind, links a workflow, and keeps one the caller cannot open unnamed", () => {
    renderWith(
      refusal([
        { kind: "workflow", id: "w1", name: "Nightly sync" },
        { kind: "table_view", id: "v1", name: "Board" },
        { kind: "table_trigger", id: "t1", name: "Follow up" },
        { kind: "table_trigger", id: "t2", name: null },
        { kind: "report", id: "r1", name: "Weekly" },
      ]),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Still used by these - change them first:");
    expect(screen.getByRole("link", { name: "Nightly sync" })).toHaveAttribute(
      "href",
      "/workflows/w1",
    );
    expect(screen.getByText("Saved view")).toBeInTheDocument();
    expect(screen.getByText("Board")).toBeInTheDocument();
    expect(screen.getAllByText("Trigger in")).toHaveLength(2);
    expect(screen.queryByRole("link", { name: "Follow up" })).not.toBeInTheDocument();
    expect(screen.getByText("One you cannot open")).toBeInTheDocument();
    expect(screen.getByText("Other")).toBeInTheDocument();
  });

  it("renders nothing for a failure that names no dependents", () => {
    const { container } = renderWith(new Error("boom"));
    expect(container).toBeEmptyDOMElement();
  });
});
