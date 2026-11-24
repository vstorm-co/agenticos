import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WorkflowMediaOperationRead, WorkflowMediaRetryEffect } from "@/lib/workflows/types";
import { makeMediaOperation } from "@/test-utils/workflow-media";

import { MediaOperationStatus, MediaRetryNotice } from "./media-operation-status";

describe("durable media status", () => {
  it("keeps held, incurred, booked and all-attempt unresolved amounts distinct", () => {
    render(<MediaOperationStatus operation={makeMediaOperation()} />);
    expect(screen.getByRole("region", { name: "Media operation" })).toBeInTheDocument();
    expect(screen.getByText("Still reserved").nextElementSibling).toHaveTextContent("$0.5000");
    expect(screen.getByText("Estimated incurred cost").nextElementSibling).toHaveTextContent(
      "$0.0200",
    );
    expect(screen.getByText("Added to run spend").nextElementSibling).toHaveTextContent("$0.0100");
    expect(
      screen.getByText("Unresolved for this step, including earlier attempts: $0.7000"),
    ).toBeInTheDocument();
    expect(screen.getByText("The final cost is not yet confirmed.")).toBeInTheDocument();
    expect(screen.queryByText("Provider receipt saved")).toBeNull();
  });

  it.each([
    ["prepared", "Ready to send"],
    ["submitting", "Sending request"],
    ["submitted", "Sent to provider"],
    ["collecting", "Collecting output"],
    ["stored", "Output saved"],
    ["unknown", "Submission status unknown"],
    ["failed", "Generation failed"],
    ["cancelled", "Generation cancelled"],
  ] as const)(
    "renders the journal phase %s without deriving it from a step status",
    (phase, text) => {
      render(<MediaOperationStatus operation={makeMediaOperation({ phase })} />);
      expect(screen.getByText(text)).toBeInTheDocument();
    },
  );

  it.each(["reported", null] as const)(
    "reports settled known costs with source %s",
    (cost_source) => {
      const operation: WorkflowMediaOperationRead = makeMediaOperation({
        cost_source,
        accounting_complete: true,
        node_unresolved_usd: "0",
        has_receipt: true,
      });
      render(<MediaOperationStatus operation={operation} />);
      expect(screen.getByText("Known incurred cost")).toBeInTheDocument();
      expect(screen.queryByText("Estimated incurred cost")).toBeNull();
      expect(screen.queryByText("The final cost is not yet confirmed.")).toBeNull();
      expect(screen.queryByText(/Unresolved for this step/)).toBeNull();
      expect(screen.getByText("Provider receipt saved")).toBeInTheDocument();
    },
  );

  it("does not call a positive fractional charge zero", () => {
    render(<MediaOperationStatus operation={makeMediaOperation({ incurred_usd: "0.000001" })} />);
    expect(screen.getByText("Estimated incurred cost").nextElementSibling).toHaveTextContent(
      "<$0.0001",
    );
  });
});

describe("the actual effect of a media retry", () => {
  it.each([
    [
      "collect_existing",
      "Use the saved provider receipt to collect the existing result. No new generation request is sent.",
    ],
    [
      "recover_output",
      "Recover this operation’s existing output. No new generation request is sent.",
    ],
    [
      "new_billable_submission",
      "This sends a new generation request and can incur another charge. Earlier unresolved charges remain reserved.",
    ],
    [
      "reconciliation_required",
      "The previous submission may have been charged. Reconcile its status before retrying this step.",
    ],
    ["none", "No media retry is available in the current state."],
  ] satisfies [WorkflowMediaRetryEffect, string][])("explains %s", (effect, text) => {
    render(<MediaRetryNotice effect={effect} />);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});
