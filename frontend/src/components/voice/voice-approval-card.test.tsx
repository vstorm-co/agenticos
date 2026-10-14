import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VoiceApprovalCard, VoiceApprovalUnavailable } from "./voice-approval-card";

const APPROVAL = {
  id: "a1",
  tool: "send_invoice",
  args: { customer: "Ahmad", amount_eur: 120, paid: false },
  said: "send an invoice for 120 euros to Ahmad",
  deadline: 61_000,
  timeoutSeconds: 60,
};

describe("VoiceApprovalCard", () => {
  it("renders the arguments verbatim and what the caller said", () => {
    render(<VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide onDecide={vi.fn()} />);
    const card = screen.getByRole("alertdialog", { name: "Approve send_invoice?" });
    expect(within(card).getByText("customer")).toBeInTheDocument();
    expect(within(card).getByText("Ahmad")).toBeInTheDocument();
    expect(within(card).getByText("120")).toBeInTheDocument();
    expect(within(card).getByText("false")).toBeInTheDocument();
    expect(within(card).getByText(/You said/)).toHaveTextContent(
      "send an invoice for 120 euros to Ahmad",
    );
  });

  it("names a tool the catalog knows by its name", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, tool: "publish_artifact", said: null }}
        now={1_000}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("alertdialog", { name: "Approve Published page?" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/You said/)).toBeNull();
  });

  it("counts down to the automatic denial", () => {
    render(<VoiceApprovalCard approval={APPROVAL} now={31_000} canDecide onDecide={vi.fn()} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "30");
    expect(screen.getByText("Denied automatically in 30 s")).toBeInTheDocument();
  });

  it("counts down over as long as the server gave", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, deadline: 31_000, timeoutSeconds: 30 }}
        now={16_000}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuemax", "30");
    expect(bar).toHaveAttribute("aria-valuenow", "15");
    expect(bar.firstElementChild).toHaveStyle({ width: "50%" });
  });

  it("never counts below zero", () => {
    render(<VoiceApprovalCard approval={APPROVAL} now={90_000} canDecide onDecide={vi.fn()} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });

  it("approves and denies by button, never by voice", () => {
    const onDecide = vi.fn();
    render(<VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide onDecide={onDecide} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    expect(onDecide.mock.calls).toEqual([[true], [false]]);
    expect(screen.getByText("Saying yes does not approve it.")).toBeInTheDocument();
  });

  it("offers no buttons to somebody who cannot decide", () => {
    render(
      <VoiceApprovalCard approval={APPROVAL} now={1_000} canDecide={false} onDecide={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("renders nested arguments as formatted JSON rather than [object Object]", () => {
    render(
      <VoiceApprovalCard
        approval={{ ...APPROVAL, args: { line: { sku: "A1", qty: 2 } } }}
        now={0}
        canDecide
        onDecide={vi.fn()}
      />,
    );
    expect(screen.getByText(/"sku": "A1"/)).toBeInTheDocument();
  });

  it("tells a caller who cannot approve, plainly, and lets them dismiss it", () => {
    const onDismiss = vi.fn();
    render(
      <VoiceApprovalUnavailable
        tool="send_invoice"
        args={{ customer: "Acme" }}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByText(/needs an approval you cannot give by voice/)).toBeInTheDocument();
    expect(screen.getByText(/"customer": "Acme"/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });
});
