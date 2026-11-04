import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";

import WorkflowLogsPage from "./page";

vi.mock("@/hooks", () => ({
  useWorkflow: () => ({ workflow: { id: "w1", name: "Lead intake" } }),
}));
vi.mock("@/components/workflows/logs/workflow-logs", () => ({
  WorkflowLogs: ({ workflowId }: { workflowId: string }) => <div>{`logs of ${workflowId}`}</div>,
}));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({
    title,
    breadcrumbs,
  }: {
    title: string;
    breadcrumbs: { label: string; href?: string }[];
  }) => (
    <div>
      <h1>{title}</h1>
      {breadcrumbs.map((crumb) => (
        <span key={crumb.label} data-href={crumb.href}>
          {crumb.label}
        </span>
      ))}
    </div>
  ),
}));

describe("a workflow's logs page", () => {
  it("names the workflow in its breadcrumbs and shows its log", async () => {
    await act(async () => {
      render(
        <Suspense fallback={null}>
          <WorkflowLogsPage params={Promise.resolve({ id: "w1" })} />
        </Suspense>,
      );
    });

    expect(screen.getByRole("heading", { name: "Logs" })).toBeInTheDocument();
    expect(screen.getByText("Lead intake")).toHaveAttribute("data-href", "/workflows/w1");
    expect(screen.getByText("logs of w1")).toBeInTheDocument();
  });
});
