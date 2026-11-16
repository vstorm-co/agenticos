import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { WorkflowRunLoading, WORKFLOW_RUN_PANELS } from "./workflow-run-loading";

it("reserves the run metrics and responsive canvas/steps layout", () => {
  const { container } = render(<WorkflowRunLoading />);
  expect(container.firstChild).toHaveAttribute("aria-busy", "true");
  expect(container.querySelectorAll("dt")).toHaveLength(3);
  expect(container.querySelector("dl")).toHaveClass("grid-cols-3");
  expect(WORKFLOW_RUN_PANELS).toContain("lg:grid-cols-[minmax(0,1fr)_22rem]");
  expect(screen.getByRole("status")).toBeInTheDocument();
});
