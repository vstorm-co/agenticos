import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { formatDateTime } from "@/lib/utils";

import { ApprovalVerdict } from "./approval-verdict";

const AT = "2026-11-13T10:28:00Z";
const WHEN = formatDateTime(AT, "en");

describe("ApprovalVerdict", () => {
  it("says who approved the step and when", () => {
    render(
      <ApprovalVerdict
        approval={{ status: "approved", decided_at: AT, decided_by_name: "Ola Nowak" }}
        output={{ decision: "approved", edited: false }}
      />,
    );
    expect(screen.getByTestId("approval-verdict")).toHaveTextContent(
      `Approved by Ola Nowak · ${WHEN}`,
    );
    expect(screen.queryByRole("button", { name: "Show changes" })).toBeNull();
  });

  it("names nobody when the decider is not given - gone, or not the reader's to see", () => {
    render(
      <ApprovalVerdict
        approval={{ status: "rejected", decided_at: AT, decided_by_name: null }}
        output={{ decision: "rejected" }}
      />,
    );
    expect(screen.getByTestId("approval-verdict")).toHaveTextContent(`Rejected · ${WHEN}`);
  });

  it("says nobody decided an expired request, or one cancelled with its run", () => {
    const { rerender } = render(
      <ApprovalVerdict
        approval={{ status: "expired", decided_at: null, decided_by_name: null }}
        output={{ decision: "expired" }}
      />,
    );
    expect(screen.getByTestId("approval-verdict")).toHaveTextContent(
      "Expired: nobody decided in time",
    );
    rerender(
      <ApprovalVerdict
        approval={{ status: "cancelled", decided_at: null, decided_by_name: null }}
        output={null}
      />,
    );
    expect(screen.getByTestId("approval-verdict")).toHaveTextContent("Cancelled with its run");
  });

  it("shows what an approver changed in the proposal, on request", async () => {
    render(
      <ApprovalVerdict
        approval={{ status: "approved", decided_at: AT, decided_by_name: "Ola" }}
        output={{
          decision: "approved",
          edited: true,
          original:
            "Hello,\nthe order\nis on\nits way\nsoon.\nThanks\nfor\nwaiting.\nRefund 40 EUR",
          final: "Hello,\nthe order\nis on\nits way\nsoon.\nThanks\nfor\nwaiting.\nRefund 45 EUR",
        }}
      />,
    );
    const toggle = screen.getByRole("button", { name: "Show changes" });
    expect(screen.queryByText("Refund 45 EUR")).toBeNull();
    await userEvent.click(toggle);
    expect(screen.getByText("Refund 45 EUR")).toBeTruthy();
    // Lines the approver left alone fold into a count.
    expect(screen.getByText(/^\d+ unchanged lines?$/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Hide changes" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });
});
